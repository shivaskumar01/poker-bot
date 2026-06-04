"""Postflop decision: equity (Monte-Carlo vs N live opponents) + pot odds + texture.

v1 models opponents as random hands, so equity is a sound but slightly optimistic estimate
when facing aggression (a bettor's range is stronger than random) — the opponent-modeling
layer narrows ranges and corrects this. Bet sizing scales with board texture; the value
threshold rises with more opponents; bluffs are suppressed multiway.
"""
from __future__ import annotations

import random
from decimal import Decimal

from ..equity.montecarlo import equity
from ..model.state import ActionType, GameState
from . import exploit, sizing
from .decision import Decision
from .mixer import Mixer

VALUE_BASE = 0.55        # heads-up equity needed to value bet
VALUE_PER_OPP = 0.04     # extra equity required per additional opponent
RAISE_MARGIN = 0.22      # equity above the call price that turns a call into a value raise


def _texture_fraction(gs: GameState) -> Decimal:
    """Pot fraction to bet/raise; wetter boards -> larger."""
    board = gs.board
    if len(board) < 3:
        return Decimal("0.50")
    suits = [c.suit for c in board]
    ranks = [c.value for c in board]
    flushy = max(suits.count(s) for s in set(suits)) >= 2
    connected = (max(ranks) - min(ranks)) <= 4
    return Decimal("0.66") if (flushy or connected) else Decimal("0.50")


def _bluff_frequency(eq: float, num_opponents: int) -> float:
    """How often to (semi-)bluff when checked to; higher equity (draws) -> more, none in a crowd."""
    if num_opponents >= 3:
        return 0.0
    base = 0.0
    if 0.30 <= eq < 0.55:
        base = 0.33 + (eq - 0.30)        # 0.33 .. 0.58
    if num_opponents == 2:
        base *= 0.4
    return min(base, 0.60)


def decide_postflop(gs: GameState, rng: random.Random | None = None,
                    iterations: int = 20_000, read=None) -> Decision:
    mx = Mixer(rng)
    hero = gs.hero
    n_opp = gs.num_live_opponents
    eq = equity(list(hero.cards), list(gs.board), n_opp, iterations=iterations, rng=rng)
    frac = _texture_fraction(gs)
    value_threshold = exploit.adj_value_threshold(
        min(0.85, VALUE_BASE + VALUE_PER_OPP * (n_opp - 1)), read)

    if gs.to_call > 0:
        required = exploit.adj_call_required(gs.pot_odds, read)  # call lighter vs maniacs
        if eq >= required + RAISE_MARGIN and eq >= value_threshold:
            return Decision(ActionType.RAISE, sizing.postflop_raise_to(gs, frac),
                            f"value raise eq={eq:.2f} vs price {required:.2f}", equity=eq)
        if eq >= required:
            return Decision(ActionType.CALL, gs.to_call,
                            f"call eq={eq:.2f} >= price {required:.2f}", equity=eq)
        return Decision(ActionType.FOLD, Decimal("0"),
                        f"fold eq={eq:.2f} < price {required:.2f}", equity=eq)

    # checked to hero (to_call == 0)
    if eq >= value_threshold:
        return Decision(ActionType.BET, sizing.postflop_bet_to(gs, frac),
                        f"value bet eq={eq:.2f} ({n_opp} opp)", equity=eq)
    p = exploit.adj_bluff_freq(_bluff_frequency(eq, n_opp), read)  # suppress vs stations, etc.
    if mx.chance(p):
        return Decision(ActionType.BET, sizing.postflop_bet_to(gs, frac),
                        f"(semi)bluff eq={eq:.2f} p={p:.2f}", equity=eq, confidence=p)
    return Decision(ActionType.CHECK, Decimal("0"), f"check eq={eq:.2f}", equity=eq)
