"""Bet/raise sizing — returns Decimal "raise-to" totals, legalized to stack & min-raise.

Sizes are computed off the amount-to-call (which we can always read) rather than per-seat
bet chips (which the live scraper can't yet read), and every result is clamped to [min legal
raise-to, hero all-in]. PokerNow takes a raise-TO amount.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from ..model.state import GameState

CENT = Decimal("0.01")


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_DOWN)


def _call_level(gs: GameState) -> Decimal:
    """Total chips hero must have in to match the current bet (= what calling makes it)."""
    return gs.hero.committed + gs.to_call


def all_in_to(gs: GameState) -> Decimal:
    return _q(gs.hero.committed + gs.hero.stack)


def can_raise(gs: GameState) -> bool:
    """Hero can raise only if they have chips beyond the call (else it's call-all-in or fold)."""
    return gs.hero.stack > gs.to_call


def legalize_raise_to(gs: GameState, target: Decimal) -> Decimal:
    """Clamp a desired raise-to into [min legal raise-to, all-in]."""
    allin = gs.hero.committed + gs.hero.stack
    min_to = _call_level(gs) + gs.min_raise
    if min_to >= allin:                      # can't make a full min-raise -> only shove is legal
        return _q(allin)
    return _q(min(max(target, min_to), allin))


def open_raise_to(gs: GameState, num_limpers: int = 0,
                  bb_multiple: Decimal = Decimal("2.5")) -> Decimal:
    bb = gs.config.big_blind
    return legalize_raise_to(gs, bb * bb_multiple + bb * num_limpers)


def threebet_to(gs: GameState, *, in_position: bool) -> Decimal:
    """3-bet to ~3x (IP) / ~4x (OOP) the raise we face."""
    mult = Decimal("3") if in_position else Decimal("4")
    return legalize_raise_to(gs, _call_level(gs) * mult)


def fourbet_to(gs: GameState) -> Decimal:
    return legalize_raise_to(gs, _call_level(gs) * Decimal("2.2"))


def postflop_bet_to(gs: GameState, pot_fraction: Decimal) -> Decimal:
    """Bet (to_call == 0): bet `pot_fraction` of the pot, never below a big blind."""
    bet = max(gs.pot * pot_fraction, gs.config.big_blind)
    return legalize_raise_to(gs, gs.hero.committed + bet)


def postflop_raise_to(gs: GameState, pot_fraction: Decimal) -> Decimal:
    """Raise facing a bet: call, then add `pot_fraction` of the resulting pot."""
    raise_size = (gs.pot + gs.to_call) * pot_fraction
    return legalize_raise_to(gs, _call_level(gs) + raise_size)
