import random
from decimal import Decimal

from pokerbot.model.cards import parse_cards
from pokerbot.model.positions import assign_positions
from pokerbot.model.state import (
    Action,
    ActionType,
    GameState,
    Seat,
    SeatStatus,
    Street,
    TableConfig,
)
from pokerbot.strategy import ranges
from pokerbot.strategy.engine import decide
from pokerbot.strategy.notation import all_hand_classes, representative_cards

D = Decimal


def rng():
    return random.Random(7)


def preflop_state(n, hero_seat, hero_cards, button=0, *, raises=(), limpers=(),
                  hero_stack="100", bb="1.0", sb="0.5"):
    bbv, sbv = D(bb), D(sb)
    order = list(range(n))
    pos = assign_positions(order, button)
    committed = {s: D("0") for s in order}
    sb_seat = next((s for s, p in pos.items() if p == "SB"), None)
    bb_seat = next(s for s, p in pos.items() if p == "BB")
    if sb_seat is not None:
        committed[sb_seat] = sbv
    committed[bb_seat] = bbv
    for s in limpers:
        committed[s] = bbv
    actions = []
    for s, amt in raises:
        committed[s] = D(amt)
        actions.append(Action(s, ActionType.RAISE, D(amt), Street.PREFLOP))
    maxc = max(committed.values())
    seats = tuple(
        Seat(seat_id=s, name=f"p{s}",
             stack=D(hero_stack) if s == hero_seat else D("100"),
             committed=committed[s], total_committed=committed[s],
             status=SeatStatus.ACTIVE,
             cards=tuple(parse_cards(hero_cards)) if s == hero_seat else (),
             is_button=(s == button), is_hero=(s == hero_seat))
        for s in order
    )
    return GameState(
        config=TableConfig(small_blind=sbv, big_blind=bbv, max_seats=n),
        seats=seats, board=(), street=Street.PREFLOP, button_seat_id=button,
        hero_seat_id=hero_seat, pot=sum(committed.values()),
        to_call=maxc - committed[hero_seat], min_raise=bbv, actions=tuple(actions),
    )


def postflop_state(n, hero_seat, hero_cards, board, button=0, *, to_call="0",
                   pot="10", hero_stack="100", live=None):
    order = list(range(n))
    live = set(order) if live is None else set(live)
    seats = tuple(
        Seat(seat_id=s, name=f"p{s}",
             stack=D(hero_stack) if s == hero_seat else D("100"),
             committed=D("0"), total_committed=D("0"),
             status=SeatStatus.ACTIVE if s in live else SeatStatus.FOLDED,
             cards=tuple(parse_cards(hero_cards)) if s == hero_seat else (),
             is_button=(s == button), is_hero=(s == hero_seat))
        for s in order
    )
    b = tuple(parse_cards(board))
    street = {0: Street.PREFLOP, 3: Street.FLOP, 4: Street.TURN, 5: Street.RIVER}.get(
        len(b), Street.FLOP)
    return GameState(
        config=TableConfig(small_blind=D("0.5"), big_blind=D("1"), max_seats=n),
        seats=seats, board=b, street=street,
        button_seat_id=button, hero_seat_id=hero_seat, pot=D(pot),
        to_call=D(to_call), min_raise=D("1"), actions=(),
    )


# ---------------- preflop ----------------

def test_open_premium_utg():
    gs = preflop_state(9, hero_seat=3, hero_cards="AhAs", button=0)  # seat 3 = UTG
    assert decide(gs, rng()).action == ActionType.RAISE


def test_fold_trash_utg():
    gs = preflop_state(9, hero_seat=3, hero_cards="7d2c", button=0)
    assert decide(gs, rng()).action == ActionType.FOLD


def test_rfi_widens_with_position():
    btn = ranges.rfi_fraction(2, is_sb=False, heads_up_match=False, blind_vs_blind=False)
    utg = ranges.rfi_fraction(8, is_sb=False, heads_up_match=False, blind_vs_blind=False)
    hu = ranges.rfi_fraction(1, is_sb=False, heads_up_match=True, blind_vs_blind=False)
    assert hu > btn > utg


def test_same_hand_opens_button_folds_utg():
    # pick a hand whose strength sits strictly between the UTG and BTN open fractions
    utg_f = ranges.rfi_fraction(8, is_sb=False, heads_up_match=False, blind_vs_blind=False)
    btn_f = ranges.rfi_fraction(2, is_sb=False, heads_up_match=False, blind_vs_blind=False)
    cls = next(c for c in all_hand_classes() if utg_f < ranges.hand_percentile(c) <= btn_f)
    cards = "".join(str(c) for c in representative_cards(cls))
    utg = decide(preflop_state(9, hero_seat=3, hero_cards=cards, button=0), rng())
    btn = decide(preflop_state(9, hero_seat=0, hero_cards=cards, button=0), rng())
    assert utg.action == ActionType.FOLD
    assert btn.action == ActionType.RAISE


def test_3bet_aces_vs_open():
    gs = preflop_state(9, hero_seat=8, hero_cards="AhAs", button=0, raises=[(3, "3.0")])
    d = decide(gs, rng())
    assert d.action == ActionType.RAISE
    assert d.amount > D("3.0")  # a real 3-bet, larger than the open


def test_fold_trash_vs_open():
    gs = preflop_state(9, hero_seat=8, hero_cards="7d2c", button=0, raises=[(3, "3.0")])
    assert decide(gs, rng()).action == ActionType.FOLD


def test_4bet_kings_vs_3bet():
    # hero (UTG seat 3) opened, CO (seat 5) 3-bet -> KK either 4-bets or traps (flats)
    gs = preflop_state(9, hero_seat=3, hero_cards="KsKd", button=0,
                       raises=[(3, "3.0"), (5, "9.0")])
    assert decide(gs, rng()).action in (ActionType.RAISE, ActionType.CALL)


def test_bb_defends_small_raise_but_folds_big_raise():
    # the leak from live play: HU BB must defend a cheap raise by price, fold an expensive one
    small = preflop_state(2, hero_seat=1, hero_cards="6h5c", button=0, raises=[(0, "2.0")])
    big = preflop_state(2, hero_seat=1, hero_cards="6h5c", button=0, raises=[(0, "8.0")])
    assert decide(small, rng()).action in (ActionType.CALL, ActionType.RAISE)
    assert decide(big, rng()).action == ActionType.FOLD


def test_short_stack_shoves_premium():
    gs = preflop_state(9, hero_seat=3, hero_cards="AhAs", button=0, hero_stack="8")
    d = decide(gs, rng())
    assert d.action == ActionType.RAISE
    assert d.amount == D("8.00")  # all-in (stack + 0 committed)


def test_short_stack_folds_trash():
    gs = preflop_state(9, hero_seat=3, hero_cards="7d2c", button=0, hero_stack="8")
    assert decide(gs, rng()).action == ActionType.FOLD


# ---------------- postflop ----------------

def test_value_bet_set_when_checked():
    gs = postflop_state(2, hero_seat=0, hero_cards="AhAd", board="As7c2d", to_call="0", pot="6")
    assert decide(gs, rng(), iterations=3000).action == ActionType.BET


def test_fold_air_vs_big_bet():
    gs = postflop_state(2, hero_seat=0, hero_cards="7c2d", board="AsKhQd", to_call="8", pot="8")
    assert decide(gs, rng(), iterations=3000).action == ActionType.FOLD


def test_no_bluff_into_a_crowd():
    # air, checked to hero, three live opponents -> never bluff
    gs = postflop_state(5, hero_seat=0, hero_cards="7c2d", board="AsKhQd",
                        to_call="0", pot="10", live={0, 1, 2, 3})
    assert decide(gs, rng(), iterations=3000).action == ActionType.CHECK


def test_call_draw_with_price():
    # nut flush draw + overcards getting 4:1 -> continue (call or raise), never fold
    gs = postflop_state(2, hero_seat=0, hero_cards="AhKh", board="Qh7h2c", to_call="3", pot="9")
    assert decide(gs, rng(), iterations=4000).action in (ActionType.CALL, ActionType.RAISE)


# ---------------- exploit integration ----------------

def test_bb_defends_marginal_hand_only_vs_maniac():
    from pokerbot.opponents.stats import PlayerStats, Stat
    # 72o: too weak to defend a normal open by price, but defendable vs a maniac's wide open
    gs = preflop_state(2, hero_seat=1, hero_cards="7d2c", button=0, raises=[(0, "3.0")])

    baseline = decide(gs, rng())
    maniac = PlayerStats("m", hands=200, agg_actions=200, call_actions=10)
    maniac.vpip = Stat(120, 200)
    maniac.pfr = Stat(95, 200)
    exploited = decide(gs, rng(), reads={0: maniac})

    assert baseline.action == ActionType.FOLD                       # too weak vs a normal open
    assert exploited.action in (ActionType.CALL, ActionType.RAISE)  # defend vs a maniac


# ---------------- stack-awareness / legal raises ----------------

def test_facing_allin_for_more_than_stack_calls_not_raises():
    # hero has a strong hand but only 1.63 left, facing a 4.13 all-in -> CALL (capped), never RAISE
    gs = postflop_state(2, hero_seat=0, hero_cards="KcAh", board="Js7s6cKhTd",
                        to_call="4.13", pot="39.60", hero_stack="1.63")
    d = decide(gs, rng(), iterations=3000)
    assert d.action == ActionType.CALL
    assert d.amount == D("1.63")          # capped to remaining stack, not a bogus raise


def test_low_spr_value_hand_commits_all_in():
    # shallow stack vs a big pot (SPR 0.5): a monster checked-to just gets it in
    gs = postflop_state(2, hero_seat=0, hero_cards="AhAd", board="As7c2d",
                        to_call="0", pot="40", hero_stack="20")
    d = decide(gs, rng(), iterations=3000)
    assert d.action == ActionType.BET
    assert d.amount == D("20.00")         # commit rather than bet an awkward fraction


def test_raise_size_is_legal_facing_a_bet():
    # a value raise must be > the amount to call (the "raise 1.63 vs 4.13 call" bug)
    gs = postflop_state(2, hero_seat=0, hero_cards="AhAd", board="As7c2d",
                        to_call="4", pot="12", hero_stack="100")
    d = decide(gs, rng(), iterations=3000)
    if d.action == ActionType.RAISE:
        assert d.amount > D("4")          # raising-to must exceed the call


# ---------------- hand-reading leaks (from live play) ----------------

def test_one_pair_river_checks_never_bluffs():
    # Hand #25 leak: KK is one pair on 4-3-7-5-A -> CHECK for showdown, never shove as a "bluff"
    gs = postflop_state(2, hero_seat=0, hero_cards="KsKd", board="4s3c7h5dAc", to_call="0", pot="56")
    assert decide(gs, rng(), iterations=3000).action == ActionType.CHECK


def test_ace_high_folds_to_bet_no_float():
    # Hand #33 leak: ace-high, no pair, no draw, facing a flop bet -> FOLD (don't float)
    gs = postflop_state(2, hero_seat=0, hero_cards="As7h", board="JsQc3d", to_call="8", pot="16")
    assert decide(gs, rng(), iterations=3000).action == ActionType.FOLD


def test_no_river_air_barrel_into_sticky_caller():
    # Hand #33 leak: ace-high air on a wet river vs a sticky lag -> almost always give up
    from pokerbot.opponents.stats import PlayerStats, Stat
    vik = PlayerStats("vik", hands=324, agg_actions=120, call_actions=40)  # loose-aggressive, sticky
    vik.vpip = Stat(130, 324)
    vik.pfr = Stat(104, 324)
    import random as _r
    bets = sum(
        decide(postflop_state(2, hero_seat=0, hero_cards="As7h", board="JsQc3d4d8d",
                              to_call="0", pot="84"),
               _r.Random(s), iterations=1200, reads={1: vik}).action == ActionType.BET
        for s in range(30)
    )
    assert bets <= 4   # gives up the river almost every time vs a caller
