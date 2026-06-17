"""Decision engine entry point, routes by street, applies exploit reads.

`reads` maps a live opponent's seat id to their PlayerStats. We pick the "primary villain",
the player we're reacting to (the aggressor when facing a bet, else the lone opponent),
and thread their read into the preflop/postflop logic, which shifts the baseline.
"""
from __future__ import annotations

import random

from ..model.state import GameState, Street
from . import postflop, preflop
from .decision import Decision


def primary_villain_read(gs: GameState, reads):
    """The read for the opponent we're reacting to, or None.

    Attribute a read ONLY when the aggressor is unambiguous: a lone live opponent, or (multiway)
    a UNIQUE strict-max committed amount that reaches the current bet level. The live scraper
    can't read per-seat bets (multiway committed is 0/blinds-only), and `max()` over equal values
    just picks an arbitrary seat, exploit deltas would fire against the WRONG person's profile.
    No read is strictly better than a wrong read; heads-up stays exact."""
    if not reads:
        return None
    live = gs.live_opponents
    if not live:
        return None
    if len(live) == 1:                                   # lone opponent: theirs, bet or checked-to
        return reads.get(live[0].seat_id)
    if gs.to_call > 0:                                   # multiway, facing a bet
        top = max(live, key=lambda s: s.committed)
        runner_up = max(s.committed for s in live if s.seat_id != top.seat_id)
        level = gs.hero.committed + gs.to_call           # current bet level (to_call may be stack-capped)
        if top.committed > runner_up and top.committed >= level:
            return reads.get(top.seat_id)                # unique max AT the bet level = the bettor
    return None                                          # ambiguous (unreadable bets): no single read


def decide(gs: GameState, rng: random.Random | None = None,
           iterations: int = 20_000, reads=None) -> Decision:
    read = primary_villain_read(gs, reads)
    if gs.street == Street.PREFLOP:
        return preflop.decide_preflop(gs, rng, read)
    return postflop.decide_postflop(gs, rng, iterations, read)
