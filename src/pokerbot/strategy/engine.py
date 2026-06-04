"""Decision engine entry point — routes by street to the preflop/postflop logic.

The exploit layer (opponent modeling) will wrap this in a later phase; for now it is the
full baseline strategy. Call `decide(game_state, rng, iterations)` to get a Decision.
"""
from __future__ import annotations

import random

from ..model.state import GameState, Street
from . import postflop, preflop
from .decision import Decision


def decide(gs: GameState, rng: random.Random | None = None,
           iterations: int = 20_000) -> Decision:
    if gs.street == Street.PREFLOP:
        return preflop.decide_preflop(gs, rng)
    return postflop.decide_postflop(gs, rng, iterations)
