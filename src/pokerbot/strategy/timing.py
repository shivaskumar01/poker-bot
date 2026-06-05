"""Action timing — how long the bot 'thinks' before it clicks, the way a human at this table does.

The dominant driver is POT SIZE (in big blinds): small pots are snappy (quick opens, limps,
auto-checks), big pots get a real think. On top of that: later streets and closer/marginal spots
take a little longer, everything gets human variance, and the bot occasionally tanks (mostly in
big pots) or snaps (mostly in small ones). It is always clamped under `max_wait` (the table's
action budget) so a tank can never run the clock out and auto-fold the bot.

Server-courtesy / realistic pacing for a DISCLOSED bot — not stealth.
"""
from __future__ import annotations

import random

from ..model.state import Street

_STREET_W = {Street.PREFLOP: 0.0, Street.FLOP: 0.5, Street.TURN: 0.8, Street.RIVER: 1.1}


def _pot_bb(gs, bb) -> float:
    try:
        b = float(bb) if bb else 1.0
        return max(0.0, float(gs.pot) / (b if b > 0 else 1.0))
    except Exception:  # noqa: BLE001
        return 0.0


def think_seconds(decision, gs, rng: random.Random, *, lo: float = 1.5, hi: float = 6.0,
                  max_wait: float | None = None, bb=None) -> float:
    """Seconds to wait before acting. `lo`/`hi` = typical think window; `max_wait` = hard ceiling
    (the action budget); `bb` = big blind, so the pot can be measured in bb. 0 when disabled (hi<=0)."""
    if hi <= 0:
        return 0.0
    cap = max(hi * 2.2, 12.0)
    if max_wait is not None:
        cap = max(0.3, min(cap, max_wait))
    pot_bb = _pot_bb(gs, bb)

    # pot size is the main driver — small pots snappy, big pots a real think (kept compact so it
    # always fits the action clock; the budget cap is the hard ceiling)
    t = 0.35 + rng.random() * 0.45                       # base reaction
    t += min(hi * 0.7, 0.25 + pot_bb * 0.06)            # ~ +0.06s per bb in the pot (capped)
    t += _STREET_W.get(gs.street, 0.4) * 0.7            # later streets a touch more
    if gs.to_call is not None and gs.to_call > 0:
        t += 0.35                                         # facing a bet
    if decision.equity is not None:                     # close/marginal spots take longer
        t += (1.0 - min(1.0, abs(decision.equity - 0.5) / 0.5)) * 0.7
    t *= 0.8 + rng.random() * 0.45                       # human variance

    # occasional tank / snap, biased by pot size (a big-pot tank, a small-pot snap)
    tank = round(min(rng.uniform(min(hi, cap), cap), cap), 1)
    snap = round(min(0.4 + rng.random() * 0.7, cap), 1)
    roll = rng.random()
    if pot_bb >= 25:                                     # big pot
        if roll < 0.22:
            return tank
        if roll > 0.95:
            return snap
    elif pot_bb <= 7:                                    # small pot
        if roll < 0.04:
            return tank
        if roll > 0.60:
            return snap
    else:                                               # medium pot
        if roll < 0.08:
            return tank
        if roll > 0.92:
            return snap
    return round(max(0.4, min(t, cap)), 1)


def tempo_label(secs: float | None, hi: float = 6.0) -> str:
    """Short human label for the UI: 'snap' / 'tank' / 'Ns'."""
    if secs is None:
        return ""
    if secs <= 1.2:
        return f"snap ({secs:g}s)"
    if secs >= hi:
        return f"tank ({secs:g}s)"
    return f"{secs:g}s"
