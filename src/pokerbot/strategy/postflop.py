"""Postflop decision: equity + pot odds + board texture, exploit- and position-aware.

Handles BOTH lines: checked-to (bet for value, (semi/pure-)bluff, or check) and facing a bet
(value-raise, semi-bluff-raise with a draw, occasional pure bluff-raise vs folders, call, or
fold). Bet sizing is opponent-aware (bigger vs stations, smaller vs nits) and randomized so
it isn't robotic. Bluff frequency keys off equity, position, opponent count, and the villain's
fold tendency (so it hammers players who fold and never bluffs calling-stations).
"""
from __future__ import annotations

import random
from decimal import Decimal

from ..equity.montecarlo import equity
from ..model.state import ActionType, GameState
from . import exploit, sizing
from .decision import Decision
from .mixer import Mixer

VALUE_BASE = 0.55         # heads-up equity needed to value bet
VALUE_PER_OPP = 0.04      # extra equity required per additional opponent
RAISE_MARGIN = 0.20       # equity above value threshold that turns a bet into a value raise
PURE_BLUFF_BASE = 0.28    # base freq to bluff pure air (heads-up, in position)
SEMIBLUFF_BASE = 0.55     # base freq to (semi-)bluff a draw


def _texture_fraction(gs: GameState) -> Decimal:
    board = gs.board
    if len(board) < 3:
        return Decimal("0.50")
    suits = [c.suit for c in board]
    ranks = [c.value for c in board]
    flushy = max(suits.count(s) for s in set(suits)) >= 2
    connected = (max(ranks) - min(ranks)) <= 4
    return Decimal("0.66") if (flushy or connected) else Decimal("0.50")


def _in_position(gs: GameState) -> bool:
    return gs.hero.is_button or gs.hero_position in ("BTN", "CO", "HJ")


def _size(gs: GameState, mx: Mixer, *, value: bool, read) -> Decimal:
    """Pot fraction with opponent adjustment + a random jitter (the 'emotion')."""
    base = float(_texture_fraction(gs))
    mult = exploit.value_size_multiplier(read) if value else exploit.bluff_size_multiplier(read)
    jitter = 0.85 + 0.33 * mx.rng.random()           # ~0.85x .. 1.18x
    frac = min(max(base * mult * jitter, 0.33), 1.25)  # cap between 1/3 pot and a 1.25x overbet
    return Decimal(str(round(frac, 2)))


def _bluff_freq(eq: float, n_opp: int, in_position: bool, read) -> float:
    if n_opp >= 3:
        return 0.0                                    # never bluff into a crowd
    if 0.30 <= eq < 0.55:
        base = SEMIBLUFF_BASE                          # a draw with real equity
    elif eq < 0.30:
        base = PURE_BLUFF_BASE                         # pure air
    else:
        base = 0.0                                     # marginal made hand -> pot control
    if not in_position:
        base *= 0.70
    if n_opp == 2:
        base *= 0.45
    return exploit.adj_bluff_freq(base, read)          # ramps vs folders, ~0 vs stations


def decide_postflop(gs: GameState, rng: random.Random | None = None,
                    iterations: int = 20_000, read=None) -> Decision:
    mx = Mixer(rng)
    hero = gs.hero
    n_opp = gs.num_live_opponents
    eq = equity(list(hero.cards), list(gs.board), n_opp, iterations=iterations, rng=rng)
    value_threshold = exploit.adj_value_threshold(
        min(0.85, VALUE_BASE + VALUE_PER_OPP * (n_opp - 1)), read)
    ip = _in_position(gs)
    is_draw = 0.30 <= eq < 0.55

    if gs.to_call > 0:                                  # facing a bet
        required = exploit.adj_call_required(gs.pot_odds, read)
        if eq >= value_threshold + RAISE_MARGIN:
            return Decision(ActionType.RAISE, sizing.postflop_raise_to(gs, _size(gs, mx, value=True, read=read)),
                            f"value raise eq={eq:.2f}", equity=eq)
        if is_draw and n_opp == 1 and mx.chance(exploit.semibluff_raise_freq(read)):
            return Decision(ActionType.RAISE, sizing.postflop_raise_to(gs, _size(gs, mx, value=False, read=read)),
                            f"semi-bluff raise eq={eq:.2f}", equity=eq, confidence=0.5)
        if eq < required and n_opp == 1 and mx.chance(exploit.bluff_raise_freq(read)):
            return Decision(ActionType.RAISE, sizing.postflop_raise_to(gs, _size(gs, mx, value=False, read=read)),
                            f"bluff raise eq={eq:.2f} (vs folder)", equity=eq, confidence=0.35)
        if eq >= required:
            return Decision(ActionType.CALL, gs.to_call, f"call eq={eq:.2f} >= price {required:.2f}", equity=eq)
        return Decision(ActionType.FOLD, Decimal("0"), f"fold eq={eq:.2f} < price {required:.2f}", equity=eq)

    # checked to hero (to_call == 0)
    if eq >= value_threshold:
        return Decision(ActionType.BET, sizing.postflop_bet_to(gs, _size(gs, mx, value=True, read=read)),
                        f"value bet eq={eq:.2f} ({n_opp} opp)", equity=eq)
    p = _bluff_freq(eq, n_opp, ip, read)
    if mx.chance(p):
        tag = "semi-bluff" if is_draw else "bluff"
        return Decision(ActionType.BET, sizing.postflop_bet_to(gs, _size(gs, mx, value=False, read=read)),
                        f"{tag} eq={eq:.2f} p={p:.2f}", equity=eq, confidence=p)
    return Decision(ActionType.CHECK, Decimal("0"), f"check eq={eq:.2f}", equity=eq)
