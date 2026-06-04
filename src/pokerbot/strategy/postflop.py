"""Postflop decision: hand-read first (made / draw / air), then equity, odds, stacks, reads.

Fixes the spew leaks: a "semi-bluff" requires an ACTUAL draw (so it can't fire on the river
or with ace-high-no-draw); made-but-not-strong hands CHECK for showdown/pot-control instead
of bluffing; pure bluffs decay hard by street and shut off vs sticky callers; and air FOLDS
to a bet instead of floating on inflated vs-random equity. Value hands still bet/raise and
commit at low SPR.
"""
from __future__ import annotations

import random
from decimal import Decimal

from ..equity.handinfo import classify_hand
from ..equity.montecarlo import equity
from ..model.state import ActionType, GameState, Street
from ..opponents.classify import classify
from . import exploit, sizing
from .decision import Decision
from .mixer import Mixer

VALUE_EQ = 0.70           # equity that makes a hand a value bet even without a "strong" category
RAISE_EQ = 0.62           # min equity to turn a value hand into a raise (vs just calling)
COMMIT_SPR = 1.5
COMMIT_EQ = 0.55
PURE_BLUFF_BASE = 0.25    # heads-up, in position, flop
SEMIBLUFF_BASE = 0.55
_STREET_DECAY = {Street.FLOP: 1.0, Street.TURN: 0.6, Street.RIVER: 0.35}
_MADE_CALL_PENALTY = {Street.FLOP: 0.06, Street.TURN: 0.10, Street.RIVER: 0.12}


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
    return Decimal(str(round(min(max(base * mult * jitter, 0.33), 1.25), 2)))


def _pure_bluff_freq(read, street: Street, in_position: bool) -> float:
    base = PURE_BLUFF_BASE * _STREET_DECAY[street]
    if not in_position:
        base *= 0.70
    if street == Street.RIVER:
        # only fire the river as a bluff vs a KNOWN folder; never into callers/unknowns
        folder = read is not None and (
            classify(read) == "nit" or read.r("fold_to_cbet_flop") > 0.55)
        if not folder:
            return 0.0
    return exploit.adj_bluff_freq(base, read)


def _semibluff_freq(read, street: Street) -> float:
    return exploit.adj_bluff_freq(SEMIBLUFF_BASE * (1.0 if street == Street.FLOP else 0.65), read)


def decide_postflop(gs: GameState, rng: random.Random | None = None,
                    iterations: int = 20_000, read=None) -> Decision:
    mx = Mixer(rng)
    hero = gs.hero
    n_opp = gs.num_live_opponents
    eq = equity(list(hero.cards), list(gs.board), n_opp, iterations=iterations, rng=rng)
    info = classify_hand(hero.cards, gs.board)
    street = gs.street
    river = street == Street.RIVER
    ip = _in_position(gs)
    raise_ok = sizing.can_raise(gs)
    value_threshold = exploit.adj_value_threshold(min(0.85, VALUE_EQ + 0.04 * (n_opp - 1)), read)
    is_value = info.strong or eq >= value_threshold
    air = not info.made and not info.draw

    if gs.to_call > 0:                                  # ---- facing a bet ----
        required = exploit.adj_call_required(gs.pot_odds, read)
        call_amt = min(gs.to_call, hero.stack)
        if raise_ok and is_value and eq >= RAISE_EQ:
            if info.strong and mx.chance(0.25):         # mix a trap with the nuts-ish
                return Decision(ActionType.CALL, call_amt, f"trap call {info.category} eq={eq:.2f}", equity=eq)
            return Decision(ActionType.RAISE,
                            _commit(gs, sizing.postflop_raise_to(gs, _size(gs, mx, value=True, read=read)), eq, value=True),
                            f"value raise {info.category} eq={eq:.2f}", equity=eq)
        if raise_ok and info.draw and not river and n_opp == 1 and mx.chance(exploit.semibluff_raise_freq(read)):
            return Decision(ActionType.RAISE,
                            _commit(gs, sizing.postflop_raise_to(gs, _size(gs, mx, value=False, read=read)), eq, value=False),
                            f"semi-bluff raise (draw) eq={eq:.2f}", equity=eq, confidence=0.5)
        if info.made and eq >= required + _MADE_CALL_PENALTY[street]:
            return Decision(ActionType.CALL, call_amt, f"call {info.category} eq={eq:.2f}", equity=eq)
        if info.draw and not river and eq >= required:
            return Decision(ActionType.CALL, call_amt, f"call draw eq={eq:.2f} (price {required:.2f})", equity=eq)
        if raise_ok and air and not river and n_opp == 1 and mx.chance(exploit.bluff_raise_freq(read)):
            return Decision(ActionType.RAISE,
                            _commit(gs, sizing.postflop_raise_to(gs, _size(gs, mx, value=False, read=read)), eq, value=False),
                            "bluff raise (vs folder)", equity=eq, confidence=0.25)
        return Decision(ActionType.FOLD, Decimal("0"), f"fold {info.category} eq={eq:.2f} < price {required:.2f}", equity=eq)

    # ---- checked to hero (to_call == 0) ----
    if is_value:
        return Decision(ActionType.BET,
                        _commit(gs, sizing.postflop_bet_to(gs, _size(gs, mx, value=True, read=read)), eq, value=True),
                        f"value bet {info.category} eq={eq:.2f} ({n_opp} opp)", equity=eq)
    if info.draw and not river and n_opp <= 2 and mx.chance(_semibluff_freq(read, street)):
        return Decision(ActionType.BET,
                        _commit(gs, sizing.postflop_bet_to(gs, _size(gs, mx, value=False, read=read)), eq, value=False),
                        f"semi-bluff (draw) eq={eq:.2f}", equity=eq, confidence=0.5)
    if air and n_opp == 1 and mx.chance(_pure_bluff_freq(read, street, ip)):
        return Decision(ActionType.BET,
                        _commit(gs, sizing.postflop_bet_to(gs, _size(gs, mx, value=False, read=read)), eq, value=False),
                        f"bluff eq={eq:.2f}", equity=eq, confidence=0.25)
    reason = "give up" if air else f"pot control / showdown ({info.category})"
    return Decision(ActionType.CHECK, Decimal("0"), f"check {reason} eq={eq:.2f}", equity=eq)
