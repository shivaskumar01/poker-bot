"""Bet/raise sizing — CLEAN, pot-relative amounts (the group bets in pot fractions/overbets).

Postflop bets are a clean fraction/multiple of the pot rounded to the big blind (½, ¾, pot,
1.5x, 2x...). Preflop raises are clean multiples of the blind; 3-bets are >=3x the open.
Everything is legalized to [min-raise, all-in]. PokerNow takes a raise-TO amount.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from ..model.state import GameState

CENT = Decimal("0.01")


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_DOWN)


def _round_amt(amount: Decimal, step: Decimal) -> Decimal:
    """Round to the nearest clean step (e.g. the big blind), so no 10.81-type bets."""
    if step <= 0:
        return amount
    return (amount / step).to_integral_value(rounding=ROUND_HALF_UP) * step


def _call_level(gs: GameState) -> Decimal:
    return gs.hero.committed + gs.to_call


def all_in_to(gs: GameState) -> Decimal:
    return _q(gs.hero.committed + gs.hero.stack)


def can_raise(gs: GameState) -> bool:
    return gs.hero.stack > gs.to_call


def legalize_raise_to(gs: GameState, target: Decimal) -> Decimal:
    allin = gs.hero.committed + gs.hero.stack
    min_to = _call_level(gs) + gs.min_raise
    if min_to >= allin:
        return _q(allin)
    return _q(min(max(target, min_to), allin))


# --- preflop (clean multiples of the blind) ---
def open_raise_to(gs: GameState, num_limpers: int = 0,
                  bb_multiple: Decimal = Decimal("3")) -> Decimal:
    bb = gs.config.big_blind
    return legalize_raise_to(gs, _round_amt(bb * bb_multiple + bb * num_limpers,
                                            gs.config.small_blind))


def threebet_to(gs: GameState, *, multiple: Decimal) -> Decimal:
    """3-bet/raise to `multiple` x the bet we face (caller passes a multiple >= 3)."""
    return legalize_raise_to(gs, _round_amt(_call_level(gs) * multiple, gs.config.small_blind))


def fourbet_to(gs: GameState, *, multiple: Decimal = Decimal("2.5")) -> Decimal:
    return legalize_raise_to(gs, _round_amt(_call_level(gs) * multiple, gs.config.small_blind))


# --- postflop (clean fraction/multiple of the pot, rounded to the big blind) ---
def postflop_bet_to(gs: GameState, pot_fraction: Decimal) -> Decimal:
    bet = max(gs.pot * pot_fraction, gs.config.big_blind)
    return legalize_raise_to(gs, _round_amt(gs.hero.committed + bet, gs.config.big_blind))


def postflop_raise_to(gs: GameState, pot_fraction: Decimal) -> Decimal:
    raise_size = (gs.pot + gs.to_call) * pot_fraction
    return legalize_raise_to(gs, _round_amt(_call_level(gs) + raise_size, gs.config.big_blind))
