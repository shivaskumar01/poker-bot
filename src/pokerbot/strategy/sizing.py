"""Bet/raise sizing. Returns Decimal "raise-to" totals, clamped to legal bounds.

PokerNow takes a raise-TO amount, so every function returns the total a player would type
into the raise box (not the increment). All results are legalized against the table's
minimum raise and the hero's stack (an over-the-top target becomes an all-in).
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from ..model.state import GameState

CENT = Decimal("0.01")


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_DOWN)


def _max_committed(gs: GameState) -> Decimal:
    return max((s.committed for s in gs.in_hand_seats), default=Decimal("0"))


def legalize_raise_to(gs: GameState, target: Decimal) -> Decimal:
    """Clamp a desired raise-to into [min legal raise-to, all-in]."""
    hero = gs.hero
    allin_to = hero.committed + hero.stack
    min_to = _max_committed(gs) + gs.min_raise
    if min_to >= allin_to:        # can't make a full min-raise -> only shove is legal
        return _q(allin_to)
    if target < min_to:
        target = min_to
    if target >= allin_to:
        return _q(allin_to)
    return _q(target)


def open_raise_to(gs: GameState, num_limpers: int = 0, bb_multiple: Decimal = Decimal("2.5")) -> Decimal:
    bb = gs.config.big_blind
    target = bb * bb_multiple + bb * num_limpers
    return legalize_raise_to(gs, target)


def threebet_to(gs: GameState, open_to: Decimal, *, in_position: bool) -> Decimal:
    mult = Decimal("3") if in_position else Decimal("4")
    return legalize_raise_to(gs, open_to * mult)


def fourbet_to(gs: GameState, threebet_amount: Decimal) -> Decimal:
    return legalize_raise_to(gs, threebet_amount * Decimal("2.2"))


def allin_to(gs: GameState) -> Decimal:
    hero = gs.hero
    return _q(hero.committed + hero.stack)


def postflop_bet_to(gs: GameState, pot_fraction: Decimal) -> Decimal:
    """Bet (to_call == 0): bet `pot_fraction` of the pot. Returns the raise-to total."""
    bet = gs.pot * pot_fraction
    target = gs.hero.committed + bet
    bb = gs.config.big_blind
    if bet < bb:                  # never bet below a big blind
        target = gs.hero.committed + bb
    return legalize_raise_to(gs, target)


def postflop_raise_to(gs: GameState, pot_fraction: Decimal) -> Decimal:
    """Raise facing a bet: raise to roughly `pot_fraction` of the post-call pot above the bet."""
    raise_size = (gs.pot + gs.to_call) * pot_fraction
    target = _max_committed(gs) + raise_size
    return legalize_raise_to(gs, target)
