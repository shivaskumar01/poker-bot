"""LiveBot, the live play loop: wait for hero's turn, scrape, decide (with reads), and (if
execute mode + consent) act, all under the SessionGuard. Defaults to observe (no clicking).
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone

from ..equity.montecarlo import recommended_iterations
from ..io.domdump import dump_dom
from ..io.prompts import EmailLogin
from ..io.scraper import infer_preflop_raise, reconstruct_preflop, to_game_state
from ..model.state import ActionType, Street
from ..opponents.aliases import canonical
from ..opponents.classify import classify
from ..strategy.engine import decide, primary_villain_read
from ..strategy.timing import tempo_label, think_seconds

_ACTION_SAFETY = 4.0   # always leave this many seconds on the clock to compute + click + register


def profile_for(store, name: str, hu: bool):
    """The table-size-appropriate profile: HU games use 'name#hu'; fall back to the other
    bucket when the right one is too thin (a person plays HU very differently from full ring)."""
    primary = store.get(name + "#hu" if hu else name)
    if primary.hands >= 15:
        return primary
    other = store.get(name if hu else name + "#hu")      # cross-bucket fallback
    return other if other.hands > primary.hands else primary


def reads_for(store, gs):
    """seat_id -> the right PlayerStats for every live opponent (aliased + table-size bucketed).
    The ONE way reads are looked up, observe.py and the live bot must never drift apart."""
    if store is None:
        return None
    hu = len(gs.dealt_seats) == 2          # heads-up table -> use HU-only reads (looser baselines)
    reads = {o.seat_id: profile_for(store, canonical(o.name), hu)
             for o in gs.live_opponents if o.name}
    return reads or None


class LiveBot:
    def __init__(self, scraper, executor, store, config, guard,
                 rng: random.Random | None = None, logfile=None,
                 on_decision=None, stop_event=None, on_status=None) -> None:
        self.scraper = scraper
        self.executor = executor
        self.store = store
        self.config = config
        self.guard = guard
        self.rng = rng or random.Random()
        self.logfile = logfile
        self.on_decision = on_decision   # callback(gs, decision, reads) for a UI
        self.on_status = on_status       # callback(dict) for blinds/stack/re-buy updates
        self.stop_event = stop_event     # threading.Event to request a stop
        self._needs_rebuy = False
        self._rebuy_requested = False
        self._last_check = 0.0
        self._login = None               # lazily-created EmailLogin (persists its inbox)
        self._play_dumps = 0             # dump the first few action-button states (turn calibration)
        self._zero_reads = 0             # consecutive 0-stack reads (debounce all-in vs real bust)
        self._hand_hole = None           # hole cards of the hand we last counted (hand boundary)
        self._last_warn = None           # last upkeep error, surfaced to the UI via on_status
        self._pre_track = None           # (hole, my_raises, my_raise_to): the bot's OWN preflop
                                         #   raises this hand, so a 3-bet of our open is priced +
                                         #   routed as a 3-bet pot (keyed by hole cards = self-resets)

    def request_rebuy(self) -> None:
        """Called from another thread (the UI), confirms a second buy-in; the bot thread
        re-anchors the bankroll on its next table check and resumes acting."""
        self._rebuy_requested = True

    def _table_check(self) -> None:
        """Out-of-turn upkeep: auto-detect (changing) blinds, track the stack for stop-loss,
        and detect a bust so the UI can ask for a re-buy. Runs in the bot (Playwright) thread.
        Errors are surfaced to the UI via on_status['warning'], not just stdout."""
        stack = None
        try:
            blinds = self.scraper.read_blinds()
            if blinds and blinds[1] > 0 and blinds[1] != self.config.big_blind:
                self.config.small_blind, self.config.big_blind = blinds
                self.guard.bb = blinds[1]
            stack = self.scraper.read_hero_stack()
            if self._rebuy_requested:
                self._rebuy_requested = False
                self._needs_rebuy = False
                self._zero_reads = 0
                if stack is not None:
                    self.guard.reset_baseline(stack)
            if stack is not None and stack > 0:
                self.guard.observe_bankroll(stack)       # only track bankroll when we actually have chips
                self._zero_reads = 0
                self._needs_rebuy = False                # has chips -> NOT busted (clears an all-in false alarm)
            elif stack is not None:                      # read a 0/negative stack
                self._zero_reads += 1                    # ... but an all-in shows 0 transiently, so debounce
                if self._zero_reads >= 4:                # sustained ~8s of 0 => a real bust
                    self._needs_rebuy = True
            # stack is None -> couldn't read this tick; leave state unchanged
            self._last_warn = None
        except Exception as e:  # noqa: BLE001 - upkeep must never crash the loop
            self._last_warn = f"table check: {e}"
            print("table-check error:", e)
        if self.on_status:
            try:
                self.on_status({
                    "small_blind": str(self.config.small_blind),
                    "big_blind": str(self.config.big_blind),
                    "stack": str(stack) if stack is not None else None,
                    "buy_in": str(self.config.buy_in),
                    "needs_rebuy": self._needs_rebuy,
                    "net_bb": round(self.guard.net_bb, 1),
                    "hands": self.guard.hands,
                    "warning": self._last_warn,
                })
            except Exception:  # noqa: BLE001 - a UI callback bug must not kill upkeep
                pass
        page = getattr(self.scraper, "page", None)   # PokerNow email-login gate (if it pops up mid-session)
        if page is not None:
            if self._login is None:
                self._login = EmailLogin(self.rng, log=lambda m: print("email-login:", m))
            try:
                self._login.run(page, self.scraper.sel, sleep=self._sleep,
                                should_stop=lambda: self.stop_event is not None
                                and self.stop_event.is_set())
            except Exception:  # noqa: BLE001
                pass

    def _sleep(self, secs: float) -> None:
        """Sleep in small steps so a Stop request is honored promptly even mid-'tank'."""
        end = time.time() + max(0.0, float(secs))
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                return
            if self.stop_event is not None and self.stop_event.is_set():
                return
            time.sleep(min(0.2, remaining))

    def _action_budget(self) -> float:
        """Max seconds we may think this turn: the live action timer minus a safety margin, or the
        configured cap when the timer can't be read, so the bot is never auto-folded."""
        try:
            left = self.scraper.read_seconds_left()
        except Exception:  # noqa: BLE001
            left = None
        if left is not None and left > 0:
            return max(0.5, left - _ACTION_SAFETY)
        return self.config.max_action_wait

    def _wait_to_act(self, secs: float) -> None:
        """Sleep up to `secs`, but bail the moment the action timer is about to expire (or Stop)."""
        end = time.time() + max(0.0, float(secs))
        check_timer = True
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                return
            if self.stop_event is not None and self.stop_event.is_set():
                return
            if check_timer:
                try:
                    left = self.scraper.read_seconds_left()
                except Exception:  # noqa: BLE001
                    left = None
                if left is None:
                    check_timer = False                 # unreadable on this table, stop polling it
                elif left <= _ACTION_SAFETY:
                    return                               # clock almost out, act NOW
            time.sleep(min(0.3, remaining))

    # --- helpers ---
    def _reads(self, gs):
        return reads_for(self.store, gs)

    def _build_state(self, raw):
        cfg = self.config
        gs = to_game_state(raw, cfg.small_blind, cfg.big_blind, cfg.hero_name)
        my_raises, my_to = 0, None
        if self._pre_track is not None and self._pre_track[0] == tuple(map(str, gs.hero.cards)):
            _, my_raises, my_to = self._pre_track
        gs = reconstruct_preflop(gs, cfg.small_blind, cfg.big_blind, hero_paid=my_to)
        return infer_preflop_raise(gs, cfg.big_blind, my_raises=my_raises)

    def _iterations(self, gs) -> int:
        """More Monte-Carlo rollouts when the pot is big, lower variance exactly where a
        close call/fold is worth real money. Small pots stay snappy."""
        cfg = self.config
        bb = float(cfg.big_blind) if cfg.big_blind else 1.0
        pot_bb = float(gs.pot) / bb if bb > 0 else 0.0
        return recommended_iterations(pot_bb, base=cfg.mc_iterations,
                                      big=cfg.mc_iterations_big_pot)

    def decide_for(self, raw):
        gs = self._build_state(raw)
        reads = self._reads(gs)
        d = decide(gs, self.rng, self._iterations(gs), reads=reads)
        return gs, d, reads

    def step(self):
        """One decision cycle (assumes it's hero's turn). Acts only if execute+consent."""
        gs, d, reads = self.decide_for(self.scraper.read_observation())
        secs = think_seconds(d, gs, self.rng, lo=self.config.min_think, hi=self.config.max_think,
                             bb=self.config.big_blind)
        self._log(gs, d)
        acted = False
        if self.executor.can_act:
            self._sleep(secs)
            acted = self.executor.execute(d)
        return gs, d, acted

    # --- the loop ---
    def run(self) -> None:
        print(f"LiveBot: mode={self.config.mode}  execute="
              f"{'ON' if self.executor.can_act else 'OFF (observe only)'}  "
              f"kill-switch=create a file named '{self.config.kill_file}' to stop\n")
        last = None          # sig we've already decided + thought about
        pending = None       # decision awaiting a successful click (retried until it lands)
        acted = False        # we've already acted this turn -> don't re-decide (avoids a phantom
                             #   second decision once our own bet registers and to-call drops to 0)
        acted_board = ()     # the board + to-call we acted on, so we can tell a genuine NEW decision
        acted_call = None    #   point (new street / a bigger bet to face) from our own action's echo
        while True:
            if self.stop_event is not None and self.stop_event.is_set():
                print("\n== stopped (requested) ==")
                return
            stop, why = self.guard.should_stop()
            if stop:
                print(f"\n== stopping: {why} | net {self.guard.net_bb:+.1f}bb over "
                      f"{self.guard.hands} hands ==")
                return
            now = time.time()
            if now - self._last_check > 2.0:        # auto-detect blinds, track stack, detect bust
                self._last_check = now
                self._table_check()
            try:
                if self._play_dumps < 6 and self.scraper.action_buttons_present():
                    self._play_dumps += 1                  # calibrate turn-detection (cheap counter gates it off)
                    page = getattr(self.scraper, "page", None)
                    if page is not None:
                        dump_dom(page, f"buttons-present is_hero_turn={self.scraper.is_hero_turn()}")
                if self.scraper.is_hero_turn():
                    raw = self.scraper.read_observation()
                    gs = self._build_state(raw)
                    sig = (tuple(map(str, gs.hero.cards)), tuple(map(str, gs.board)),
                           str(gs.to_call), gs.street.name)
                    # Re-arm the "already acted" latch the moment this is a GENUINELY new decision:
                    # a new street (board changed) or a bigger bet to face (to-call went up). Without
                    # this, closing a street (e.g. calling preflop) and then being first to act on the
                    # flop would stay latched and the bot would never act on the flop.
                    if acted and (sig[1] != acted_board
                                  or (acted_call is not None and gs.to_call > acted_call)):
                        acted = False
                    # Decide ONLY on a complete read, and ONLY once per turn. Skip if the hole cards
                    # haven't rendered yet (a scrape miss -> would size off nothing), or if we've
                    # already acted this turn. The latter is the "dashboard says 20 but bet 26" bug:
                    # after our raise registers, to-call drops to 0, sig changes, and the loop would
                    # otherwise re-decide the SAME hand to a fresh (random-sized) raise and show that.
                    if sig != last and len(gs.hero.cards) == 2 and not acted:
                        last = sig
                        # Hand boundary = NEW hole cards seen preflop. (The old `to_call <= bb`
                        # proxy never counted hands where someone raised before hero's first
                        # decision, so max_hands and the hands display under-counted.)
                        if gs.street == Street.PREFLOP and sig[0] != self._hand_hole:
                            self._hand_hole = sig[0]
                            self.guard.observe_bankroll(gs.hero.stack)
                            self.guard.count_hand()
                        reads = self._reads(gs)
                        d = decide(gs, self.rng, self._iterations(gs), reads=reads)
                        budget = self._action_budget()
                        big_pot = float(gs.pot) >= 18 * float(self.config.big_blind)
                        if big_pot and self.executor.can_act and not self._needs_rebuy:
                            self.executor.activate_extra_time()   # any big-pot decision (incl. a jam-call): buy clock
                        if d.action in (ActionType.BET, ActionType.RAISE):
                            budget = max(0.5, budget - 1.5)       # reserve time for the multi-step bet panel
                        secs = think_seconds(d, gs, self.rng, lo=self.config.min_think,
                                             hi=self.config.max_think, bb=self.config.big_blind,
                                             max_wait=budget)
                        self._announce(gs, d, reads, secs)
                        self._log(gs, d)
                        if self.on_decision is not None:
                            self.on_decision(gs, d, reads, secs)
                        if self.executor.can_act and not self._needs_rebuy:
                            self._wait_to_act(secs)      # human-paced, but never past the action clock
                            if self.scraper.is_hero_turn():
                                pending = d              # STILL our turn after the think -> act
                            else:
                                pending, last = None, None   # turn passed during the think -> re-read fresh
                        else:
                            pending = None
                    if pending is not None and self.executor.execute(pending):
                        if gs.street == Street.PREFLOP and pending.action is ActionType.RAISE:
                            same = self._pre_track is not None and self._pre_track[0] == sig[0]
                            n = self._pre_track[1] + 1 if same else 1
                            self._pre_track = (sig[0], n, pending.amount)   # our open/3-bet, by hole
                        pending, acted = None, True        # clicked through -> latch; else retry next loop
                        acted_board, acted_call = sig[1], gs.to_call   # remember WHAT we acted on
                else:
                    # turn passed -> drop any stale action, re-arm, and FORGET the last sig: if an
                    # execute was refused (controls weren't live) the same sig may come back on the
                    # REAL turn and must be re-decided fresh, not skipped as a duplicate.
                    pending, acted, last = None, False, None
            except Exception as e:  # noqa: BLE001 - keep the session alive through transient errors
                print("loop error:", e)
            time.sleep(0.1)         # fast poll so the bot detects its turn quickly on fast tables

    # --- output ---
    def _announce(self, gs, d, reads, secs=None) -> None:
        villain = primary_villain_read(gs, reads)
        vtag = f"  vs {classify(villain)}" if villain and villain.hands >= 15 else ""
        hole = " ".join(map(str, gs.hero.cards)) or "??"
        board = " ".join(map(str, gs.board)) or "-"
        amt = f" {d.amount}" if d.action.name in ("BET", "RAISE") else ""
        eq = f" eq={d.equity:.2f}" if d.equity is not None else ""
        tempo = tempo_label(secs, self.config.max_think)
        tempo = f"  [{tempo}]" if (tempo and self.executor.can_act) else ""
        verb = "WOULD" if not self.executor.can_act else ">>"
        print(f"[{gs.street.name}] {hole} | board {board} | pos {gs.hero_position} | "
              f"{gs.num_live_opponents} opp | pot {gs.pot} to-call {gs.to_call}{vtag}")
        print(f"   {verb} {d.action.name}{amt}{eq}{tempo}   {d.rationale}\n")

    def _log(self, gs, d) -> None:
        if not self.logfile:
            return
        self.logfile.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(), "street": gs.street.name,
            "hole": [str(c) for c in gs.hero.cards], "board": [str(c) for c in gs.board],
            "pot": str(gs.pot), "to_call": str(gs.to_call),
            "action": d.action.name, "amount": str(d.amount),
            "equity": d.equity, "rationale": d.rationale,
        }) + "\n")
        self.logfile.flush()
