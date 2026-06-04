import random

from pokerbot.equity.montecarlo import equity
from pokerbot.model.cards import parse_cards


def test_aces_vs_one_random():
    eq = equity(parse_cards("AsAc"), [], 1, iterations=30_000, rng=random.Random(42))
    assert 0.83 < eq < 0.87  # known ~85.2%


def test_aces_multiway_monotonic_decrease():
    e1 = equity(parse_cards("AsAc"), [], 1, iterations=20_000, rng=random.Random(1))
    e3 = equity(parse_cards("AsAc"), [], 3, iterations=20_000, rng=random.Random(2))
    e5 = equity(parse_cards("AsAc"), [], 5, iterations=20_000, rng=random.Random(3))
    assert e1 > e3 > e5            # more opponents -> less equity
    assert 0.59 < e3 < 0.69        # known ~63.7%


def test_made_nuts_full_board_wins_always():
    # As Ks + Qs Js Ts = royal flush; unbeatable and untieable -> equity exactly 1.0
    eq = equity(parse_cards("AsKs"), parse_cards("QsJsTs2h3d"), 1, iterations=2_000)
    assert eq == 1.0


def test_royal_on_board_everyone_ties():
    # Board itself is a royal flush; hero junk plays the board, so does villain -> 0.5
    eq = equity(parse_cards("2c7d"), parse_cards("AsKsQsJsTs"), 1, iterations=2_000)
    assert eq == 0.5


def test_invalid_inputs_raise():
    import pytest

    with pytest.raises(ValueError):
        equity(parse_cards("As"), [], 1)            # 1 hole card
    with pytest.raises(ValueError):
        equity(parse_cards("AsAc"), [], 0)          # 0 opponents
    with pytest.raises(ValueError):
        equity(parse_cards("AsAc"), parse_cards("2h3d4s5c6h7s"), 1)  # 6-card board
