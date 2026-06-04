"""Decision engine entry point — routes by street, applies exploit reads.

`reads` maps a live opponent's seat id to their PlayerStats. We pick the "primary villain"
— the player we're reacting to (the aggressor when facing a bet, else the lone opponent) —
and thread their read into the preflop/postflop logic, which shifts the baseline.
"""
from __future__ import annotations

import random

from ..model.state import GameState, Street
from . import postflop, preflop
from .decision import Decision


def primary_villain_read(gs: GameState, reads):
    """The read for the opponent we're reacting to, or None."""
    if not reads:
        return None
    live = gs.live_opponents
    if not live:
        return None
    if gs.to_call > 0:                                   # react to the aggressor
        aggressor = max(live, key=lambda s: s.committed)
        return reads.get(aggressor.seat_id)
    if len(live) == 1:                                   # heads-up pot, lone opponent
        return reads.get(live[0].seat_id)
    return None                                          # multiway checked-to: no single read


def decide(gs: GameState, rng: random.Random | None = None,
           iterations: int = 20_000, reads=None) -> Decision:
    read = primary_villain_read(gs, reads)
    if gs.street == Street.PREFLOP:
        return preflop.decide_preflop(gs, rng, read)
    return postflop.decide_postflop(gs, rng, iterations, read)
