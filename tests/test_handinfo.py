from pokerbot.equity.handinfo import classify_hand
from pokerbot.model.cards import parse_cards as P


def hb(hole, board):
    return classify_hand(tuple(P(hole)), tuple(P(board)))


def test_overpair_strong():
    i = hb("KsKd", "4s3c7h")
    assert i.made and i.strong and not i.draw


def test_one_pair_below_an_overcard_is_made_not_strong():
    # KK on 4-3-7-5-A: a made pair (showdown value) but NOT strong (ace overcard), no draw
    i = hb("KsKd", "4s3c7h5dAc")
    assert i.made and not i.strong and not i.draw


def test_top_pair_is_strong():
    i = hb("AhKc", "Ks7d2c")    # top pair (kings)
    assert i.made and i.strong


def test_ace_high_no_draw_is_air():
    i = hb("As7h", "JsQc3d")
    assert not i.made and not i.draw and not i.strong


def test_flush_draw_is_a_draw():
    i = hb("AhKh", "Qh7h2c")
    assert i.draw and not i.made


def test_no_draws_on_the_river():
    i = hb("9c4d", "KsQh2d7s8c")  # river, ace-high junk
    assert not i.draw and not i.made
