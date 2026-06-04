import csv

from pokerbot.io.log_parser import parse_file, parse_glyph_card
from pokerbot.model.cards import Card
from pokerbot.opponents.tracking import accumulate


def _write_log(path, entries):
    """entries: list of entry strings in chronological order."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["entry", "at", "order"])
        for i, e in enumerate(entries):
            w.writerow([e, "2026-01-01T00:00:00Z", 1000 + i])


HAND1 = [
    '-- starting hand #1 (id: t1)  No Limit Texas Hold\'em (dealer: "C @ c") --',
    'Player stacks: #1 "A @ a" (100.00) | #2 "B @ b" (100.00) | #3 "C @ c" (100.00)',
    '"A @ a" posts a small blind of 1.00',
    '"B @ b" posts a big blind of 2.00',
    "Your hand is A♠, K♠",
    '"C @ c" raises to 6.00',            # open (PFR for C)
    '"A @ a" folds',
    '"B @ b" raises to 18.00',           # 3-bet by B
    '"C @ c" calls 18.00',               # C faces a 3-bet and calls
    "Flop:  [K♣, 7♥, 2♦]",
    '"B @ b" bets 20.00',                # B is preflop aggressor -> c-bet
    '"C @ c" folds',                     # C folds to the c-bet
    '"B @ b" collected 41.00 from pot',
    "-- ending hand #1 --",
]

HAND2 = [
    '-- starting hand #2 (id: t2)  No Limit Texas Hold\'em (dealer: "A @ a") --',
    'Player stacks: #1 "A @ a" (120.00) | #2 "B @ b" (80.00)',
    '"B @ b" posts a small blind of 1.00',
    '"A @ a" posts a big blind of 2.00',
    '"B @ b" raises to 6.00',
    '"A @ a" calls 6.00',
    "Flop:  [Q♠, Q♦, 2♣]",
    '"A @ a" checks', '"B @ b" bets 8.00', '"A @ a" calls 8.00',
    "Turn: Q♠, Q♦, 2♣ [3♥]",
    '"A @ a" checks', '"B @ b" checks',
    "River: Q♠, Q♦, 2♣, 3♥ [5♠]",
    '"A @ a" checks', '"B @ b" checks',
    '"B @ b" shows a J♥, K♦.',           # two-card show on one line
    '"A @ a" shows a A♣, Q♥.',
    '"A @ a" collected 28.00 from pot',
    "-- ending hand #2 --",
]


def test_glyph_cards():
    assert parse_glyph_card("10♥") == Card("T", "h")
    assert parse_glyph_card("A♠") == Card("A", "s")
    assert parse_glyph_card("K♦") == Card("K", "d")


def test_parse_structure(tmp_path):
    p = tmp_path / "log.csv"
    _write_log(p, HAND1 + HAND2)
    hands = parse_file(str(p))
    assert len(hands) == 2
    h1 = hands[0]
    assert h1.number == 1 and h1.dealer_id == "c"
    assert set(h1.stacks) == {"a", "b", "c"}
    assert h1.hero_cards == [Card("A", "s"), Card("K", "s")]
    assert h1.board == [Card("K", "c"), Card("7", "h"), Card("2", "d")]
    # two-card show line splits correctly
    assert hands[1].shows["b"] == [Card("J", "h"), Card("K", "d")]
    assert hands[1].board[-1] == Card("5", "s")  # river appended


def test_accumulate_stats(tmp_path):
    p = tmp_path / "log.csv"
    _write_log(p, HAND1)
    stats: dict = {}
    for h in parse_file(str(p)):
        accumulate(stats, h)

    a, b, c = stats["a"], stats["b"], stats["c"]
    assert a.vpip.raw == 0.0 and a.pfr.raw == 0.0          # SB then fold = not voluntary
    assert c.vpip.raw == 1.0 and c.pfr.raw == 1.0          # opened
    assert b.threebet.made == 1 and b.threebet.opp == 1    # B 3-bet the open
    assert c.fold_to_3bet.opp == 1 and c.fold_to_3bet.made == 0  # C called the 3-bet
    assert b.cbet_flop.made == 1                           # B c-bet as PF aggressor
    assert c.fold_to_cbet_flop.made == 1                   # C folded to it
    assert b.agg_actions == 1 and b.call_actions == 0      # one postflop bet
