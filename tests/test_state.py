from dataclasses import replace
from decimal import Decimal

from pokerbot.model.state import (
    GameState,
    Seat,
    SeatStatus,
    Street,
    TableConfig,
)

D = Decimal


def _seat(sid, stack, committed=D("0"), status=SeatStatus.ACTIVE, hero=False, button=False):
    return Seat(
        seat_id=sid,
        name=f"p{sid}",
        stack=D(str(stack)),
        committed=D(str(committed)),
        total_committed=D(str(committed)),
        status=status,
        is_hero=hero,
        is_button=button,
    )


def _six_handed():
    cfg = TableConfig(small_blind=D("0.50"), big_blind=D("1.00"), max_seats=6)
    seats = (
        _seat(0, 100, button=True),       # BTN
        _seat(1, 100, committed="0.50"),  # SB
        _seat(2, 100, committed="1.00"),  # BB
        _seat(3, 100, hero=True),         # UTG (hero)
        _seat(4, 100),                    # MP
        _seat(5, 40),                     # CO (short stack)
    )
    return GameState(
        config=cfg,
        seats=seats,
        board=(),
        street=Street.PREFLOP,
        button_seat_id=0,
        hero_seat_id=3,
        pot=D("1.50"),
        to_call=D("1.00"),
        min_raise=D("1.00"),
    )


def test_live_opponent_count():
    assert _six_handed().num_live_opponents == 5


def test_positions_full_table():
    gs = _six_handed()
    assert gs.positions == {0: "BTN", 1: "SB", 2: "BB", 3: "UTG", 4: "MP", 5: "CO"}
    assert gs.hero_position == "UTG"


def test_folded_seat_keeps_position_but_not_live():
    gs = _six_handed()
    seats = tuple(
        replace(s, status=SeatStatus.FOLDED) if s.seat_id == 4 else s for s in gs.seats
    )
    gs2 = replace(gs, seats=seats)
    assert gs2.num_live_opponents == 4                  # one fewer live opponent
    assert set(gs2.positions) == {0, 1, 2, 3, 4, 5}     # position fixed at deal — seat 4 still MP
    assert gs2.positions[4] == "MP"


def test_pot_odds_and_spr():
    gs = _six_handed()
    assert abs(gs.pot_odds - 0.4) < 1e-9          # 1.0 / (1.5 + 1.0)
    assert abs(gs.spr - (100 / 1.5)) < 1e-6


def test_effective_stack_uses_smaller():
    gs = _six_handed()
    assert gs.effective_stack(5) == D("40")        # hero 100 vs CO 40
    assert gs.effective_stack(4) == D("100")


def test_big_blinds_conversion():
    assert _six_handed().big_blinds(D("10")) == 10.0
