from decimal import Decimal

from pokerbot.io.executor import Executor
from pokerbot.io.scraper import (
    RawObservation,
    RawSeat,
    card_from_classes,
    parse_blinds_text,
    parse_card_text,
    parse_money,
    to_game_state,
)
from pokerbot.io.selectors import Selectors
from pokerbot.model.cards import Card
from pokerbot.model.state import ActionType, SeatStatus, Street
from pokerbot.strategy.decision import Decision

D = Decimal


def test_parse_money():
    assert parse_money("461.58") == D("461.58")
    assert parse_money("1,234.50") == D("1234.50")
    assert parse_money("1.2K") == D("1200.0")
    assert parse_money("$25") == D("25")
    assert parse_money("0\n\ntotal 0") == D("0")     # PokerNow pot element text
    assert parse_money("") == D("0")


def test_parse_blinds_text():
    assert parse_blinds_text("Blinds: 0.50/1.00") == (D("0.50"), D("1.00"))
    assert parse_blinds_text("NL Hold'em 1 / 2") == (D("1"), D("2"))
    assert parse_blinds_text("No Limit Hold'em $2/$5") == (D("2"), D("5"))
    assert parse_blinds_text("blinds 5/10 ante 1") == (D("5"), D("10"))   # ignore ante (10 > 5*3? no)
    assert parse_blinds_text("no blinds here") is None
    assert parse_blinds_text("ratio 1/100") is None                      # not a sane sb/bb pair


def test_parse_card_text_glyph_and_ascii():
    assert parse_card_text("10♥") == Card("T", "h")
    assert parse_card_text("A♠") == Card("A", "s")
    assert parse_card_text("Kd") == Card("K", "d")


def _three_handed_preflop():
    return RawObservation(
        seats=[
            RawSeat(0, "Hero", "100", bet="1", is_hero=True),       # SB
            RawSeat(1, "Villain1", "100", bet="2"),                 # BB
            RawSeat(2, "Villain2", "100", bet="0", is_button=True),  # BTN
        ],
        board=[],
        pot="0",
    )


def test_to_game_state_assembly():
    gs = to_game_state(_three_handed_preflop(), D("1"), D("2"))
    assert gs.street == Street.PREFLOP
    assert gs.hero_seat_id == 0 and gs.button_seat_id == 2
    assert gs.to_call == D("1")                  # BB 2 - hero SB 1
    assert gs.pot == D("3")                       # 0 collected + (1 + 2 + 0) on the felt
    assert gs.positions == {2: "BTN", 0: "SB", 1: "BB"}
    assert gs.hero_position == "SB"


def test_to_game_state_postflop_street_from_board():
    raw = _three_handed_preflop()
    raw.board = ["A♠", "K♦", "2♣"]
    raw.seats[2].is_button = True
    gs = to_game_state(raw, D("1"), D("2"))
    assert gs.street == Street.FLOP
    assert gs.board == (Card("A", "s"), Card("K", "d"), Card("2", "c"))


def test_card_from_classes():
    assert card_from_classes("card-container card-d  card-s-6 flipped card-p1 med") == Card("6", "d")
    assert card_from_classes("card-container card-s  card-s-7 flipped big") == Card("7", "s")
    assert card_from_classes("card-container card-c  card-s-K flipped big") == Card("K", "c")
    assert card_from_classes("card-container card-h  card-s-10 flipped") == Card("T", "h")
    assert card_from_classes("table-cards run-1") is None        # not a card container


def test_to_game_state_real_heads_up_hand():
    # the exact hand captured by the live probe: hero "robot" 6d4h vs vik, flop 7s2dKc
    raw = RawObservation(
        seats=[
            RawSeat(1, "robot", "48.00", is_hero=True, cards=["6d", "4h"]),
            RawSeat(7, "vik", "48.00"),
        ],
        board=["7s", "2d", "Kc"],
        pot="4.00\n\ntotal 4.00",
        to_call="0",                 # check button present -> nothing to call
        button_seat_id=7,            # from .dealer-position-7
    )
    gs = to_game_state(raw, D("0.5"), D("1"))
    assert gs.street == Street.FLOP
    assert gs.button_seat_id == 7 and gs.hero_seat_id == 1
    assert gs.to_call == D("0") and gs.pot == D("4.00")
    assert gs.num_live_opponents == 1
    assert gs.hero_position == "BB"      # HU: button=vik(7), hero(1)=BB
    assert gs.hero.cards == (Card("6", "d"), Card("4", "h"))
    assert gs.board == (Card("7", "s"), Card("2", "d"), Card("K", "c"))


def test_reconstruct_preflop_fixes_pot_and_committed():
    from pokerbot.io.scraper import reconstruct_preflop
    # live: hero BB, villain raised to 2.0; scraper read pot=0 with no per-seat bets
    raw = RawObservation(
        seats=[RawSeat(1, "robot", "100", is_hero=True), RawSeat(7, "vik", "100")],
        board=[], pot="0", to_call="1.0", button_seat_id=7,
    )
    gs = to_game_state(raw, D("0.5"), D("1.0"))
    assert gs.pot == D("0")                       # broken before reconstruction
    fixed = reconstruct_preflop(gs, D("0.5"), D("1.0"))
    assert fixed.hero.committed == D("1.0")        # hero's BB
    assert fixed.seat(7).committed == D("2.0")     # raiser total = BB + to_call
    assert fixed.pot == D("3.0")
    assert abs(fixed.pot_odds - (1.0 / 4.0)) < 1e-9  # now a sane price, not ~1.0


def test_executor_consent_gate():
    # observe mode: never acts, never touches the (None) page
    ex = Executor(page=None, selectors=Selectors(), mode="observe", players_consent=False)
    assert ex.can_act is False
    assert ex.execute(Decision(ActionType.RAISE, D("10"), "x")) is False
    # execute mode but no consent: still refuses
    assert Executor(None, Selectors(), mode="execute", players_consent=False).can_act is False
    # only execute + consent unlocks acting
    assert Executor(None, Selectors(), mode="execute", players_consent=True).can_act is True
