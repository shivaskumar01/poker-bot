"""Preflop decision: classify the situation, then apply the parameterized ranges.

Situations: short-stack push/fold, open-or-fold (RFI), isolate-limpers, facing a raise
(3bet/call/fold + a small suited bluff-3bet frequency), facing a 3bet (4bet/call/fold), and
facing a 4bet+ (shove/call/fold). Everything keys off table size and position via the
number of players left to act, computed live from the dealt seats.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from ..model.positions import postflop_action_order, preflop_action_order
from ..model.state import ActionType, GameState, SeatStatus, Street
from . import ranges, sizing
from .decision import Decision
from .mixer import Mixer
from .notation import canonical, is_suited

PUSH_FOLD_BB = 12.0
LATE_POSITIONS = {"CO", "BTN", "SB", "HJ"}


@dataclass(frozen=True, slots=True)
class _Ctx:
    hero_pos: str
    heads_up_match: bool
    lone_opponent: bool
    blind_vs_blind: bool
    is_sb: bool
    is_bb: bool
    players_left: int          # active seats still to act after hero, preflop
    num_raises: int
    num_limpers: int
    aggressor: int | None
    in_position: bool          # hero acts after the aggressor postflop
    vs_late_open: bool


def _max_committed(gs: GameState) -> Decimal:
    return max((s.committed for s in gs.in_hand_seats), default=Decimal("0"))


def _context(gs: GameState) -> _Ctx:
    order = gs.seats_clockwise_dealt
    pre = preflop_action_order(order, gs.button_seat_id)
    post = postflop_action_order(order, gs.button_seat_id)
    positions = gs.positions
    hero_id = gs.hero_seat_id
    hero_pos = positions.get(hero_id, "?")

    pre_actions = [a for a in gs.actions if a.street == Street.PREFLOP]
    raises = [a for a in pre_actions if a.action == ActionType.RAISE]
    num_raises = len(raises)
    aggressor = raises[-1].seat_id if raises else None

    bb = gs.config.big_blind
    num_limpers = 0
    if num_raises == 0:
        num_limpers = sum(
            1 for s in gs.live_opponents
            if s.committed == bb and positions.get(s.seat_id) != "BB"
        )

    hero_i = pre.index(hero_id)
    players_left = sum(
        1 for sid in pre[hero_i + 1:] if gs.seat(sid).status is SeatStatus.ACTIVE
    )

    lone = gs.num_live_opponents == 1
    is_sb = hero_pos == "SB"
    in_position = False
    vs_late = False
    if aggressor is not None and aggressor in post and hero_id in post:
        in_position = post.index(hero_id) > post.index(aggressor)
        vs_late = positions.get(aggressor) in LATE_POSITIONS

    return _Ctx(
        hero_pos=hero_pos,
        heads_up_match=len(order) == 2,
        lone_opponent=lone,
        blind_vs_blind=is_sb and lone,
        is_sb=is_sb,
        is_bb=hero_pos == "BB",
        players_left=players_left,
        num_raises=num_raises,
        num_limpers=num_limpers,
        aggressor=aggressor,
        in_position=in_position,
        vs_late_open=vs_late,
    )


def decide_preflop(gs: GameState, rng: random.Random | None = None) -> Decision:
    mx = Mixer(rng)
    ctx = _context(gs)
    cls = canonical(*gs.hero.cards)
    pct = ranges.hand_percentile(cls)
    hero_bb = float(gs.hero.stack / gs.config.big_blind)

    if hero_bb <= PUSH_FOLD_BB:
        return _push_fold(gs, ctx, cls, pct, hero_bb)
    if ctx.num_raises == 0:
        return (_open_or_fold if ctx.num_limpers == 0 else _iso_or_fold)(gs, ctx, cls, pct)
    if ctx.num_raises == 1:
        return _vs_raise(gs, ctx, cls, pct, mx)
    if ctx.num_raises == 2:
        return _vs_3bet(gs, ctx, cls, pct)
    return _vs_4bet_plus(gs, cls, pct)


def _open_or_fold(gs, ctx, cls, pct):
    frac = ranges.rfi_fraction(ctx.players_left, is_sb=ctx.is_sb,
                               heads_up_match=ctx.heads_up_match, blind_vs_blind=ctx.blind_vs_blind)
    if pct <= frac:
        return Decision(ActionType.RAISE, sizing.open_raise_to(gs, 0),
                        f"open {cls} ({ctx.hero_pos}, top {frac:.0%})")
    if gs.to_call <= 0:
        return Decision(ActionType.CHECK, Decimal("0"), f"check {cls} (option)")
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} (outside RFI {frac:.0%})")


def _iso_or_fold(gs, ctx, cls, pct):
    frac = ranges.iso_fraction(ctx.players_left, ctx.num_limpers, is_sb=ctx.is_sb,
                               heads_up_match=ctx.heads_up_match, blind_vs_blind=ctx.blind_vs_blind)
    if pct <= frac:
        return Decision(ActionType.RAISE, sizing.open_raise_to(gs, ctx.num_limpers),
                        f"isolate {cls} over {ctx.num_limpers} limper(s)")
    if gs.to_call <= 0:
        return Decision(ActionType.CHECK, Decimal("0"), f"check {cls} in limped pot")
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs limpers")


def _vs_raise(gs, ctx, cls, pct, mx):
    tb, cont = ranges.vs_raise_thresholds(
        in_position=ctx.in_position, players_left_behind=ctx.players_left,
        vs_late_open=ctx.vs_late_open, is_bb=ctx.is_bb)
    open_to = _max_committed(gs)
    if pct <= tb:
        return Decision(ActionType.RAISE, sizing.threebet_to(gs, open_to, in_position=ctx.in_position),
                        f"value 3-bet {cls}")
    if pct <= cont:
        return Decision(ActionType.CALL, gs.to_call, f"call raise with {cls} (top {cont:.0%})")
    if is_suited(cls) and pct <= cont * 1.5 and mx.chance(0.5):
        return Decision(ActionType.RAISE, sizing.threebet_to(gs, open_to, in_position=ctx.in_position),
                        f"bluff 3-bet {cls}", confidence=0.5)
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs raise")


def _vs_3bet(gs, ctx, cls, pct):
    fourbet, cont = ranges.vs_3bet_thresholds(in_position=ctx.in_position)
    if pct <= fourbet:
        return Decision(ActionType.RAISE, sizing.fourbet_to(gs, _max_committed(gs)),
                        f"4-bet value {cls}")
    if pct <= cont:
        return Decision(ActionType.CALL, gs.to_call, f"call 3-bet {cls}")
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs 3-bet")


def _vs_4bet_plus(gs, cls, pct):
    if pct <= 0.015:
        return Decision(ActionType.RAISE, sizing.allin_to(gs), f"5-bet shove {cls}")
    if pct <= 0.030:
        return Decision(ActionType.CALL, gs.to_call, f"call 4-bet {cls}")
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs 4-bet+")


def _push_fold(gs, ctx, cls, pct, hero_bb):
    if ctx.num_raises == 0:
        frac = ranges.push_fraction(ctx.players_left, hero_bb, is_sb=ctx.is_sb,
                                    lone_opponent=ctx.lone_opponent)
        if pct <= frac:
            return Decision(ActionType.RAISE, sizing.allin_to(gs),
                            f"shove {cls} ({hero_bb:.0f}bb, top {frac:.0%})")
        if gs.to_call <= 0:
            return Decision(ActionType.CHECK, Decimal("0"), "check (short, no raise)")
        return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} (short)")
    frac = ranges.call_allin_fraction(hero_bb, in_position=ctx.in_position)
    if pct <= frac:
        return Decision(ActionType.RAISE, sizing.allin_to(gs), f"re-shove {cls} (short)")
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs raise (short)")
