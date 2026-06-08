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


def test_open_ender_is_a_draw_but_gutshot_is_not():
    assert hb("7h6c", "8s9c2d").draw          # 6-7-8-9 open-ender
    assert not hb("8c6c", "8s5s9s").draw      # 5-6-_-8-9 gutshot (+ pair) -> not a draw to raise
    assert not hb("Td6c", "7s8s2d").draw      # 6-7-8-_-T gutshot


def test_no_draws_on_the_river():
    i = hb("9c4d", "KsQh2d7s8c")  # river, ace-high junk
    assert not i.draw and not i.made


def test_board_only_flush_draw_is_not_heros_draw():
    # FOUR hearts on the board but hero holds none -> NOT a draw the hero can semi-bluff
    i = hb("AsKd", "Qh7h2h9h")
    assert not i.draw
    # but with one heart in hand (4 total, hero contributes) it IS the hero's flush draw
    assert hb("Ah2c", "Qh7h9h").draw


def test_board_only_straight_draw_is_not_heros_draw():
    # 6-7-8-9 sits entirely on the board; hero's offsuit blanks don't share the run
    i = hb("AsKd", "6h7c8s9d")
    assert not i.draw
    # hero holding the 9 (using a hole card in the run) IS an open-ender
    assert hb("9h2c", "6h7c8s4d").draw


def test_incomplete_hole_cards_never_crash():
    # the "can't read hands" guard: a momentary scrape miss (0 or 1 hole card) must not raise
    assert classify_hand((), tuple(P("KsQh2d"))) == classify_hand((), tuple(P("KsQh2d")))
    i = classify_hand(tuple(P("Ah")), tuple(P("KsQh2d")))   # only one card read
    assert not i.made and not i.strong and not i.draw       # treated as air, no exception
