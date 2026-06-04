"""LiveBot — the live play loop: wait for hero's turn, scrape, decide (with reads), and (if
execute mode + consent) act, all under the SessionGuard. Defaults to observe (no clicking).
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import replace
from datetime import datetime, timezone

from ..io.prompts import resolve_email_login
from ..io.scraper import reconstruct_preflop, to_game_state
from ..model.state import Action, ActionType, Street
from ..opponents.classify import classify
from ..strategy.engine import decide, primary_villain_read
from ..strategy.timing import tempo_label, think_seconds


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
                if stack is not None:
                    self.guard.reset_baseline(stack)
            if stack is not None:
                self.guard.observe_bankroll(stack)
                if stack <= 0:
                    self._needs_rebuy = True
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
            try:
                resolve_email_login(page, self.scraper.sel, self.rng, sleep=self._sleep,
                                    log=lambda m: print("email-login:", m),
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
        secs = think_seconds(d, gs, self.rng, lo=self.config.min_think, hi=self.config.max_think)
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
        last = None
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
                        secs = think_seconds(d, gs, self.rng,
                                             lo=self.config.min_think, hi=self.config.max_think)
                        self._announce(gs, d, reads, secs)
                        self._log(gs, d)
                        if self.on_decision is not None:
                            self.on_decision(gs, d, reads, secs)
                        if self.executor.can_act and not self._needs_rebuy:
                            self._sleep(secs)            # human-paced + timing-tell balanced
                            self.executor.execute(d)
            except Exception as e:  # noqa: BLE001 - keep the session alive through transient errors
                print("loop error:", e)
            time.sleep(0.2)

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
