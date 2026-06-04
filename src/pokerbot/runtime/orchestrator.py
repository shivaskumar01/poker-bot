"""LiveBot — the live play loop: wait for hero's turn, scrape, decide (with reads), and (if
execute mode + consent) act, all under the SessionGuard. Defaults to observe (no clicking).
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import replace
from datetime import datetime, timezone

from ..io.scraper import reconstruct_preflop, to_game_state
from ..model.state import Action, ActionType, Street
from ..opponents.classify import classify
from ..strategy.engine import decide, primary_villain_read


class LiveBot:
    def __init__(self, scraper, executor, store, config, guard,
                 rng: random.Random | None = None, logfile=None) -> None:
        self.scraper = scraper
        self.executor = executor
        self.store = store
        self.config = config
        self.guard = guard
        self.rng = rng or random.Random()
        self.logfile = logfile

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
        self._log(gs, d)
        acted = False
        if self.executor.can_act:
            self.guard.think()
            acted = self.executor.execute(d)
        return gs, d, acted

    # --- the loop ---
    def run(self) -> None:
        print(f"LiveBot: mode={self.config.mode}  execute="
              f"{'ON' if self.executor.can_act else 'OFF (observe only)'}  "
              f"kill-switch=create a file named '{self.config.kill_file}' to stop\n")
        last = None
        while True:
            stop, why = self.guard.should_stop()
            if stop:
                print(f"\n== stopping: {why} | net {self.guard.net_bb:+.1f}bb over "
                      f"{self.guard.hands} hands ==")
                return
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
                        self._announce(gs, d, reads)
                        self._log(gs, d)
                        if self.executor.can_act:
                            self.guard.think()
                            self.executor.execute(d)
            except Exception as e:  # noqa: BLE001 - keep the session alive through transient errors
                print("loop error:", e)
            time.sleep(0.2)

    # --- output ---
    def _announce(self, gs, d, reads) -> None:
        villain = primary_villain_read(gs, reads)
        vtag = f"  vs {classify(villain)}" if villain and villain.hands >= 15 else ""
        hole = " ".join(map(str, gs.hero.cards)) or "??"
        board = " ".join(map(str, gs.board)) or "-"
        amt = f" {d.amount}" if d.action.name in ("BET", "RAISE") else ""
        eq = f" eq={d.equity:.2f}" if d.equity is not None else ""
        verb = "WOULD" if not self.executor.can_act else ">>"
        print(f"[{gs.street.name}] {hole} | board {board} | pos {gs.hero_position} | "
              f"{gs.num_live_opponents} opp | pot {gs.pot} to-call {gs.to_call}{vtag}")
        print(f"   {verb} {d.action.name}{amt}{eq}   {d.rationale}\n")

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
