from pokerbot.model.positions import (
    POSITION_LABELS,
    assign_positions,
    postflop_action_order,
    preflop_action_order,
)


def test_heads_up_button_is_sb():
    pos = assign_positions([1, 2], button=1)
    assert pos[1] == "BTN"
    assert pos[2] == "BB"


def test_six_max_labels_clockwise():
    seats = [0, 1, 2, 3, 4, 5]
    pos = assign_positions(seats, button=0)
    assert [pos[s] for s in seats] == ["BTN", "SB", "BB", "UTG", "MP", "CO"]


def test_ten_max_full_continuum():
    seats = list(range(10))
    pos = assign_positions(seats, button=0)
    assert [pos[s] for s in seats] == POSITION_LABELS[10]


def test_button_offset_rotation():
    seats = [0, 1, 2, 3, 4, 5]
    pos = assign_positions(seats, button=3)
    assert pos[3] == "BTN"
    assert pos[4] == "SB"
    assert pos[5] == "BB"
    assert pos[0] == "UTG"


def test_preflop_first_actor():
    assert preflop_action_order(list(range(9)), button=0)[0] == 3  # UTG
    assert preflop_action_order([0, 1], button=0)[0] == 0          # HU: BTN acts first
    assert preflop_action_order([0, 1, 2], button=0)[0] == 0       # 3-handed: BTN first


def test_postflop_button_last():
    order = postflop_action_order(list(range(9)), button=0)
    assert order[0] == 1   # SB first
    assert order[-1] == 0  # button last
    hu = postflop_action_order([0, 1], button=0)
    assert hu[0] == 1 and hu[-1] == 0  # HU: BB first, BTN last


def test_unsupported_size_raises():
    import pytest

    with pytest.raises(ValueError):
        assign_positions([0], button=0)        # 1 player
    with pytest.raises(ValueError):
        assign_positions(list(range(11)), 0)   # 11 players
