"""Action timing — how long the bot 'thinks' before it clicks.

Two jobs:
  1. Act at a human, server-courteous pace in a DISCLOSED game (never instantaneous, never timing
     out the action clock).
  2. Avoid TIMING TELLS. The think time is built from spot *complexity* only — street, whether
     we're facing a bet, how marginal the spot is, how committed we'd get — and is deliberately
     INDEPENDENT of hand strength. Then a fraction of the time we deliberately TANK or SNAP,
     chosen at random regardless of strength. So a tank-raise with the nuts is indistinguishable
     from a tank-bluff, and a snap-call with a monster from a snap bluff-catch.

This is poker strategy (balancing your timing the way a thinking player does), not stealth.
"""
from __future__ import annotations

import random

from ..model.state import ActionType, Street

_STREET_W = {Street.PREFLOP: 0.0, Street.FLOP: 0.7, Street.TURN: 1.1, Street.RIVER: 1.7}

P_TANK = 0.12     # deliberately go into the tank ...
P_SNAP = 0.20     # ... or snap, on top of the tank chance (so ~12% tank, ~20% snap, ~68% normal)


def think_seconds(decision, gs, rng: random.Random, *, lo: float = 1.5, hi: float = 6.0,
                  max_wait: float | None = None) -> float:
    """Seconds to wait before acting. `lo`/`hi` are the typical think window (config min/max);
    `max_wait` is a hard ceiling (the table's action budget) so a 'tank' can never run the clock
    out. Returns 0 when timing is disabled (hi<=0) so tests/headless runs don't sleep."""
    if hi <= 0:
        return 0.0
    cap = max(hi * 2.2, 12.0)                       # tank ceiling
    if max_wait is not None:                        # ... but never exceed the action budget
        cap = max(0.3, min(cap, max_wait))

    # --- complexity, computed WITHOUT reference to hand strength so the clock can't leak it ---
    t = 0.7 + rng.random() * 0.9                    # base reaction time
    t += _STREET_W.get(gs.street, 0.8)              # later streets = more to think about
    facing = gs.to_call is not None and gs.to_call > 0
    if facing:
        t += 0.8
    if decision.action in (ActionType.BET, ActionType.RAISE):
        t += 0.7
    if decision.action == ActionType.FOLD:
        t -= 0.3                                     # give-ups come a touch quicker
    if decision.equity is not None:                 # marginal spots (equity ~50%) take longer
        t += (1.0 - min(1.0, abs(decision.equity - 0.5) / 0.5)) * 1.3
    try:                                            # the more committed we'd get, the longer we think
        call = float(gs.to_call or 0)
        t += min(1.5, call / max(1.0, float(gs.hero.stack) + call) * 2.0)
    except Exception:  # noqa: BLE001
        pass
    t *= 0.85 + rng.random() * 0.4                  # natural jitter
    t = max(lo * 0.5, t)

    # --- timing-tell balancing: tank/snap chosen independently of strength ---
    roll = rng.random()
    if roll < P_TANK:
        return round(rng.uniform(min(hi, cap), cap), 1)     # into the tank (within budget)
    if roll < P_TANK + P_SNAP:
        return round(min(0.4 + rng.random() * 0.6, cap), 1)  # snap
    return round(min(t, cap), 1)


def tempo_label(secs: float | None, hi: float = 6.0) -> str:
    """Short human label for the UI: 'snap' / 'tank' / 'Ns'."""
    if secs is None:
        return ""
    if secs <= 1.2:
        return f"snap ({secs:g}s)"
    if secs >= hi:
        return f"tank ({secs:g}s)"
    return f"{secs:g}s"
