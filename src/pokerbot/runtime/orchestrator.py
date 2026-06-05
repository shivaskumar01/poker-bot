"""LiveBot — the live play loop: wait for hero's turn, scrape, decide (with reads), and (if
execute mode + consent) act, all under the SessionGuard. Defaults to observe (no clicking).
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import replace
from datetime import datetime, timezone

from ..io.domdump import dump_dom
from ..io.prompts import EmailLogin
from ..io.scraper import reconstruct_preflop, to_game_state
from ..model.state import Action, ActionType, Street
from ..opponents.classify import classify
from ..strategy.engine import decide, primary_villain_read
from ..strategy.timing import tempo_label, think_seconds

_ACTION_SAFETY = 4.0   # always leave this many seconds on the clock to compute + click + register


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

    def request_rebuy(self) -> None:
        """Called from another thread (the UI) — confirms a second buy-in; the bot thread
        re-anchors the bankroll on its next table check and resumes acting."""
        self._rebuy_requested = True

    def _table_check(self) -> None:
        """Out-of-turn upkeep: auto-detect (changing) blinds, track the stack for stop-loss,
        and detect a bust so the UI can ask for a re-buy. Runs in the bot (Playwright) thread."""
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
            if self.on_status:
                self.on_status({
                    "small_blind": str(self.config.small_blind),
                    "big_blind": str(self.config.big_blind),
                    "stack": str(stack) if stack is not None else None,
                    "buy_in": str(self.config.buy_in),
                    "needs_rebuy": self._needs_rebuy,
                    "net_bb": round(self.guard.net_bb, 1),
                    "hands": self.guard.hands,
                })
        except Exception as e:  # noqa: BLE001 - upkeep must never crash the loop
            print("table-check error:", e)
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
        configured cap when the timer can't be read — so the bot is never auto-folded."""
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
                    check_timer = False                 # unreadable on this table — stop polling it
                elif left <= _ACTION_SAFETY:
                    return                               # clock almost out — act NOW
            time.sleep(min(0.3, remaining))

    # --- helpers ---
    def _reads(self, gs):
        if self.store is None:
            return None
        reads = {o.seat_id: self.store.get(o.name) for o in gs.live_opponents if o.name}
        return reads or None

    def _build_state(self, raw):
        cfg = self.config
        gs = reconstruct_preflop(
            to_game_state(raw, cfg.small_blind, cfg.big_blind, cfg.hero_name),
            cfg.small_blind, cfg.big_blind)
        if gs.street == Street.PREFLOP and gs.to_call > cfg.big_blind and gs.live_opponents:
            o = gs.live_opponents[0]   # heads-up: treat as facing a raise so the engine 3bets/calls
            gs = replace(gs, actions=(Action(o.seat_id, ActionType.RAISE,
                                             gs.to_call + gs.hero.committed, Street.PREFLOP),))
        return gs

    def decide_for(self, raw):
        gs = self._build_state(raw)
        reads = self._reads(gs)
        d = decide(gs, self.rng, self.config.mc_iterations, reads=reads)
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
                if self.scraper.action_buttons_present() and self._play_dumps < 8:
                    self._play_dumps += 1                  # calibrate turn-detection (seat classes etc.)
                    page = getattr(self.scraper, "page", None)
                    if page is not None:
                        dump_dom(page, f"buttons-present is_hero_turn={self.scraper.is_hero_turn()}")
                if self.scraper.is_hero_turn():
                    raw = self.scraper.read_observation()
                    gs = self._build_state(raw)
                    sig = (tuple(map(str, gs.hero.cards)), tuple(map(str, gs.board)),
                           str(gs.to_call), gs.street.name)
                    if sig != last:
                        last = sig
                        if gs.street == Street.PREFLOP:           # hand-boundary bankroll/hand tracking
                            self.guard.observe_bankroll(gs.hero.stack)
                            if gs.to_call <= self.config.big_blind:
                                self.guard.count_hand()
                        reads = self._reads(gs)
                        d = decide(gs, self.rng, self.config.mc_iterations, reads=reads)
                        secs = think_seconds(d, gs, self.rng, lo=self.config.min_think,
                                             hi=self.config.max_think, bb=self.config.big_blind,
                                             max_wait=self._action_budget())
                        self._announce(gs, d, reads, secs)
                        self._log(gs, d)
                        if self.on_decision is not None:
                            self.on_decision(gs, d, reads, secs)
                        if self.executor.can_act and not self._needs_rebuy:
                            self._wait_to_act(secs)      # human-paced, but never past the action clock
                            pending = d
                        else:
                            pending = None
                    if pending is not None and self.executor.execute(pending):
                        pending = None                   # clicked through; else retry next loop
                else:
                    pending = None                       # not our turn anymore — drop any stale action
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
