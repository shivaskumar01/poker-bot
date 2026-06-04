"""Postflop decision: equity + pot odds + board texture + STACK DEPTH, exploit-aware.

Stack-aware: sizes are capped at the effective stack, and at low SPR (stacks shallow vs the
pot) with a real hand it just commits (shoves) instead of betting an awkward fraction.
Raising is gated on actually being able to raise — facing an all-in for more than hero's
stack, the only choices are call (all-in) or fold.
"""
from __future__ import annotations

import random
from decimal import Decimal

from ..equity.montecarlo import equity
from ..model.state import ActionType, GameState
from . import exploit, sizing
from .decision import Decision
from .mixer import Mixer

VALUE_BASE = 0.55
VALUE_PER_OPP = 0.04
RAISE_MARGIN = 0.20
PURE_BLUFF_BASE = 0.28
SEMIBLUFF_BASE = 0.55
COMMIT_SPR = 1.5          # at/below this stack-to-pot ratio, get strong hands all-in
COMMIT_EQ = 0.55          # ...if equity is at least this


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


def _effective_stack(gs: GameState) -> Decimal:
    opp = [o.stack for o in gs.live_opponents]
    return min(gs.hero.stack, max(opp)) if opp else gs.hero.stack


def _spr(gs: GameState) -> float:
    return float(_effective_stack(gs)) / float(gs.pot) if gs.pot > 0 else 99.0


def _commit(gs: GameState, target: Decimal, eq: float, *, value: bool) -> Decimal:
    """Round a sized bet up to all-in when committing makes sense (low SPR value, or the
    sizing already puts most of the stack in)."""
    allin = gs.hero.committed + gs.hero.stack
    if value and eq >= COMMIT_EQ and _spr(gs) <= COMMIT_SPR:
        return allin
    if target >= Decimal("0.66") * allin:
        return allin
    return target


def _size(gs: GameState, mx: Mixer, *, value: bool, read) -> Decimal:
    base = float(_texture_fraction(gs))
    mult = exploit.value_size_multiplier(read) if value else exploit.bluff_size_multiplier(read)
    jitter = 0.85 + 0.33 * mx.rng.random()
    frac = min(max(base * mult * jitter, 0.33), 1.25)
    return Decimal(str(round(frac, 2)))


def _bluff_freq(eq: float, n_opp: int, in_position: bool, read) -> float:
    if n_opp >= 3:
        return 0.0
    if 0.30 <= eq < 0.55:
        base = SEMIBLUFF_BASE
    elif eq < 0.30:
        base = PURE_BLUFF_BASE
    else:
        base = 0.0
    if not in_position:
        base *= 0.70
    if n_opp == 2:
        base *= 0.45
    return exploit.adj_bluff_freq(base, read)


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
    raise_ok = sizing.can_raise(gs)               # False when calling would be all-in

    if gs.to_call > 0:                            # facing a bet
        required = exploit.adj_call_required(gs.pot_odds, read)
        call_amt = min(gs.to_call, hero.stack)    # capped: calling can be all-in for less
        if raise_ok and eq >= value_threshold + RAISE_MARGIN:
            tgt = _commit(gs, sizing.postflop_raise_to(gs, _size(gs, mx, value=True, read=read)), eq, value=True)
            return Decision(ActionType.RAISE, tgt, f"value raise eq={eq:.2f}", equity=eq)
        if raise_ok and is_draw and n_opp == 1 and mx.chance(exploit.semibluff_raise_freq(read)):
            tgt = _commit(gs, sizing.postflop_raise_to(gs, _size(gs, mx, value=False, read=read)), eq, value=False)
            return Decision(ActionType.RAISE, tgt, f"semi-bluff raise eq={eq:.2f}", equity=eq, confidence=0.5)
        if raise_ok and eq < required and n_opp == 1 and mx.chance(exploit.bluff_raise_freq(read)):
            tgt = _commit(gs, sizing.postflop_raise_to(gs, _size(gs, mx, value=False, read=read)), eq, value=False)
            return Decision(ActionType.RAISE, tgt, f"bluff raise eq={eq:.2f} (vs folder)", equity=eq, confidence=0.35)
        if eq >= required:
            return Decision(ActionType.CALL, call_amt, f"call eq={eq:.2f} >= price {required:.2f}", equity=eq)
        return Decision(ActionType.FOLD, Decimal("0"), f"fold eq={eq:.2f} < price {required:.2f}", equity=eq)

    # checked to hero (to_call == 0)
    if eq >= value_threshold:
        tgt = _commit(gs, sizing.postflop_bet_to(gs, _size(gs, mx, value=True, read=read)), eq, value=True)
        return Decision(ActionType.BET, tgt, f"value bet eq={eq:.2f} ({n_opp} opp)", equity=eq)
    p = _bluff_freq(eq, n_opp, ip, read)
    if mx.chance(p):
        tag = "semi-bluff" if is_draw else "bluff"
        tgt = _commit(gs, sizing.postflop_bet_to(gs, _size(gs, mx, value=False, read=read)), eq, value=False)
        return Decision(ActionType.BET, tgt, f"{tag} eq={eq:.2f} p={p:.2f}", equity=eq, confidence=p)
    return Decision(ActionType.CHECK, Decimal("0"), f"check eq={eq:.2f}", equity=eq)
