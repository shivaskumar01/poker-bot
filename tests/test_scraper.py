from decimal import Decimal

from pokerbot.io.executor import Executor
from pokerbot.io.scraper import (
    RawObservation,
    RawSeat,
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
    assert parse_money("") == D("0")


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


def test_executor_consent_gate():
    # observe mode: never acts, never touches the (None) page
    ex = Executor(page=None, selectors=Selectors(), mode="observe", players_consent=False)
    assert ex.can_act is False
    assert ex.execute(Decision(ActionType.RAISE, D("10"), "x")) is False
    # execute mode but no consent: still refuses
    assert Executor(None, Selectors(), mode="execute", players_consent=False).can_act is False
    # only execute + consent unlocks acting
    assert Executor(None, Selectors(), mode="execute", players_consent=True).can_act is True
