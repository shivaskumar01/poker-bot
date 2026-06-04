"""Preflop decision: classify the situation, then apply ranges + pot-odds defense.

Less exploitable by design: it DEFENDS BY PRICE (call when hand equity beats the pot odds,
so it can't be run over by small raises), MIXES open sizing, 3-bet-bluffs a real polar range
(suited + blocker hands), occasionally slow-plays premiums, and widens/tightens off the
opponent read. Raising is gated on actually being able to raise (else call all-in / fold).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from ..model.positions import postflop_action_order, preflop_action_order
from ..model.state import ActionType, GameState, SeatStatus, Street
from ..opponents.classify import classify
from . import exploit, ranges, sizing
from .decision import Decision
from .mixer import Mixer
from .notation import canonical, is_suited

PUSH_FOLD_BB = 12.0
LATE_POSITIONS = {"CO", "BTN", "SB", "HJ"}
SLOWPLAY_FREQ = 0.25          # how often to flat (trap) instead of re-raising a premium vs a 3-bet


@dataclass(frozen=True, slots=True)
class _Ctx:
    hero_pos: str
    heads_up_match: bool
    lone_opponent: bool
    blind_vs_blind: bool
    is_sb: bool
    is_bb: bool
    players_left: int
    num_raises: int
    num_limpers: int
    aggressor: int | None
    in_position: bool
    vs_late_open: bool


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

    hero_i = pre.index(hero_id) if hero_id in pre else 0
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
        hero_pos=hero_pos, heads_up_match=len(order) == 2, lone_opponent=lone,
        blind_vs_blind=is_sb and lone, is_sb=is_sb, is_bb=hero_pos == "BB",
        players_left=players_left, num_raises=num_raises, num_limpers=num_limpers,
        aggressor=aggressor, in_position=in_position, vs_late_open=vs_late,
    )


def _call_amount(gs: GameState) -> Decimal:
    return min(gs.to_call, gs.hero.stack)


def _open_to(gs: GameState, mx: Mixer, read, num_limpers: int = 0) -> Decimal:
    """Opponent-aware open size in CLEAN multiples: bigger vs loose callers (charge them),
    smaller vs nits. Varies between clean sizes for unpredictability (never min-raises loose)."""
    if read is not None and read.confidence >= exploit.MIN_CONF:
        label = classify(read)
        if label in ("station", "lag", "maniac") or read.r("vpip") >= 0.35:
            mult = mx.choose([(Decimal("3.0"), 3.0), (Decimal("4.0"), 1.0)])  # loose -> 3x mostly, some 4x
        elif label == "nit":
            mult = Decimal("2.0")
        else:
            mult = mx.choose([(Decimal("2.5"), 2.0), (Decimal("3.0"), 1.0)])
    else:
        mult = mx.choose([(Decimal("2.5"), 2.0), (Decimal("3.0"), 1.0)])
    return sizing.open_raise_to(gs, num_limpers, mult)


def _is_3bet_bluff(cls: str) -> bool:
    # polar bluffs: suited hands (playable) or ace/king-high (card-removal blockers)
    return is_suited(cls) or cls[0] in ("A", "K")


def _is_4bet_bluff(cls: str) -> bool:
    return cls[0] == "A" and is_suited(cls)       # suited aces: best blockers


def decide_preflop(gs: GameState, rng: random.Random | None = None, read=None) -> Decision:
    mx = Mixer(rng)
    ctx = _context(gs)
    cls = canonical(*gs.hero.cards)
    pct = ranges.hand_percentile(cls)
    hero_bb = float(gs.hero.stack / gs.config.big_blind)
    raise_ok = sizing.can_raise(gs)

    if hero_bb <= PUSH_FOLD_BB:
        return _push_fold(gs, ctx, cls, pct, hero_bb, raise_ok)
    if ctx.num_raises == 0:
        fn = _open_or_fold if ctx.num_limpers == 0 else _iso_or_fold
        return fn(gs, ctx, cls, pct, raise_ok, mx, read)
    if ctx.num_raises == 1:
        return _vs_raise(gs, ctx, cls, pct, mx, read, raise_ok)
    if ctx.num_raises == 2:
        return _vs_3bet(gs, ctx, cls, pct, mx, read, raise_ok)
    return _vs_4bet_plus(gs, cls, pct, raise_ok)


def _open_or_fold(gs, ctx, cls, pct, raise_ok, mx, read):
    frac = ranges.rfi_fraction(ctx.players_left, is_sb=ctx.is_sb,
                               heads_up_match=ctx.heads_up_match, blind_vs_blind=ctx.blind_vs_blind)
    if pct <= frac:
        if raise_ok:
            return Decision(ActionType.RAISE, _open_to(gs, mx, read),
                            f"open {cls} ({ctx.hero_pos}, top {frac:.0%})")
        return Decision(ActionType.CALL, _call_amount(gs), f"call all-in {cls} (short)")
    if gs.to_call <= 0:
        return Decision(ActionType.CHECK, Decimal("0"), f"check {cls} (option)")
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} (outside RFI {frac:.0%})")


def _iso_or_fold(gs, ctx, cls, pct, raise_ok, mx, read):
    frac = ranges.iso_fraction(ctx.players_left, ctx.num_limpers, is_sb=ctx.is_sb,
                               heads_up_match=ctx.heads_up_match, blind_vs_blind=ctx.blind_vs_blind)
    if pct <= frac and raise_ok:
        return Decision(ActionType.RAISE, _open_to(gs, mx, read, ctx.num_limpers),
                        f"isolate {cls} over {ctx.num_limpers} limper(s)")
    if gs.to_call <= 0:
        return Decision(ActionType.CHECK, Decimal("0"), f"check {cls} in limped pot")
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs limpers")


def _vs_raise(gs, ctx, cls, pct, mx, read, raise_ok):
    tb, _cont = ranges.vs_raise_thresholds(
        in_position=ctx.in_position, players_left_behind=ctx.players_left,
        vs_late_open=ctx.vs_late_open, is_bb=ctx.is_bb)
    tb, _ = exploit.adj_vs_raise(tb, _cont, read)
    heads_up = ctx.heads_up_match or ctx.lone_opponent

    if pct <= tb and raise_ok:                                  # polarized value 3-bet
        return Decision(ActionType.RAISE, sizing.threebet_to(gs, in_position=ctx.in_position),
                        f"value 3-bet {cls}")

    thr = exploit.adj_defense_threshold(
        ranges.defense_equity_threshold(gs.pot_odds, in_position=ctx.in_position,
                                        vs_late_open=ctx.vs_late_open, heads_up=heads_up), read)
    if ranges.hand_equity(cls) >= thr:                          # defend by price
        return Decision(ActionType.CALL, _call_amount(gs),
                        f"call {cls} (eq {ranges.hand_equity(cls):.2f} >= price {thr:.2f})")

    if raise_ok and _is_3bet_bluff(cls) and mx.chance(exploit.adj_3bet_bluff_freq(0.30, read)):
        return Decision(ActionType.RAISE, sizing.threebet_to(gs, in_position=ctx.in_position),
                        f"3-bet bluff {cls}", confidence=0.3)
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs raise")


def _vs_3bet(gs, ctx, cls, pct, mx, read, raise_ok):
    fourbet, _cont = ranges.vs_3bet_thresholds(in_position=ctx.in_position)
    if pct <= fourbet and raise_ok:
        if mx.chance(SLOWPLAY_FREQ):                            # trap: flat the premium sometimes
            return Decision(ActionType.CALL, _call_amount(gs), f"flat (trap) {cls} vs 3-bet")
        return Decision(ActionType.RAISE, sizing.fourbet_to(gs), f"4-bet value {cls}")

    thr = ranges.threebet_call_equity_threshold(gs.pot_odds, in_position=ctx.in_position)
    if ranges.hand_equity(cls) >= thr:
        return Decision(ActionType.CALL, _call_amount(gs), f"call 3-bet {cls} (price)")

    if raise_ok and _is_4bet_bluff(cls) and mx.chance(exploit.adj_3bet_bluff_freq(0.15, read)):
        return Decision(ActionType.RAISE, sizing.fourbet_to(gs), f"4-bet bluff {cls}", confidence=0.15)
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs 3-bet")


def _vs_4bet_plus(gs, cls, pct, raise_ok):
    if pct <= 0.015:
        if raise_ok:
            return Decision(ActionType.RAISE, sizing.all_in_to(gs), f"5-bet shove {cls}")
        return Decision(ActionType.CALL, _call_amount(gs), f"call all-in {cls}")
    if pct <= 0.030:
        return Decision(ActionType.CALL, _call_amount(gs), f"call 4-bet {cls}")
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs 4-bet+")


def _push_fold(gs, ctx, cls, pct, hero_bb, raise_ok):
    if ctx.num_raises == 0:
        frac = ranges.push_fraction(ctx.players_left, hero_bb, is_sb=ctx.is_sb,
                                    lone_opponent=ctx.lone_opponent)
        if pct <= frac:
            if raise_ok:
                return Decision(ActionType.RAISE, sizing.all_in_to(gs),
                                f"shove {cls} ({hero_bb:.0f}bb, top {frac:.0%})")
            return Decision(ActionType.CALL, _call_amount(gs), f"call all-in {cls} (short)")
        if gs.to_call <= 0:
            return Decision(ActionType.CHECK, Decimal("0"), "check (short, no raise)")
        return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} (short)")
    frac = ranges.call_allin_fraction(hero_bb, in_position=ctx.in_position)
    if pct <= frac:
        if raise_ok:
            return Decision(ActionType.RAISE, sizing.all_in_to(gs), f"re-shove {cls} (short)")
        return Decision(ActionType.CALL, _call_amount(gs), f"call all-in {cls} (short)")
    return Decision(ActionType.FOLD, Decimal("0"), f"fold {cls} vs raise (short)")
