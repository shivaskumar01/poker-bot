"""Scrape PokerNow's DOM into a GameState.

Split into a **pure assembly core** (raw observation -> GameState, fully unit-tested) and a
thin **DOM-reading layer** (Playwright queries via Selectors, calibrated live). The DOM layer
fills a RawObservation; `to_game_state` turns it into the canonical model the engine consumes.
Money/cards parsing handles both glyph (♠) and ascii (s) suits and comma/K/M formatting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..model.cards import Card
from ..model.state import (
    GameState,
    Seat,
    SeatStatus,
    Street,
    TableConfig,
)

_SUIT_GLYPH = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}
_STATUS_MAP = {
    "active": SeatStatus.ACTIVE, "folded": SeatStatus.FOLDED, "all_in": SeatStatus.ALL_IN,
    "allin": SeatStatus.ALL_IN, "sitting_out": SeatStatus.SITTING_OUT,
    "away": SeatStatus.AWAY, "empty": SeatStatus.EMPTY,
}
_STREET_BY_BOARD = {0: Street.PREFLOP, 3: Street.FLOP, 4: Street.TURN, 5: Street.RIVER}


def parse_money(s: str) -> Decimal:
    s = s.strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    if not s:
        return Decimal("0")
    mult = 1
    if s[-1] in "KkMm":
        mult = {"k": 1000, "m": 1_000_000}[s[-1].lower()]
        s = s[:-1]
    try:
        return Decimal(s) * mult
    except Exception:
        return Decimal("0")


def parse_card_text(s: str) -> Card:
    s = s.strip()
    if s[-1] in _SUIT_GLYPH:
        suit, rank = _SUIT_GLYPH[s[-1]], s[:-1]
    else:
        suit, rank = s[-1].lower(), s[:-1]
    if rank == "10":
        rank = "T"
    return Card(rank.upper(), suit)


@dataclass
class RawSeat:
    seat_id: int
    name: str | None
    stack: str
    bet: str = ""
    status: str = "active"
    is_button: bool = False
    is_hero: bool = False
    cards: list[str] = field(default_factory=list)


@dataclass
class RawObservation:
    seats: list[RawSeat]
    board: list[str] = field(default_factory=list)
    pot: str = "0"


def to_game_state(raw: RawObservation, small_blind: Decimal, big_blind: Decimal,
                  hero_name: str | None = None, actions=()) -> GameState:
    """Pure assembly: RawObservation -> GameState. Raises if hero can't be identified."""
    seats: list[Seat] = []
    for rs in raw.seats:
        committed = parse_money(rs.bet) if rs.bet else Decimal("0")
        seats.append(Seat(
            seat_id=rs.seat_id, name=rs.name, stack=parse_money(rs.stack),
            committed=committed, total_committed=committed,
            status=_STATUS_MAP.get(rs.status, SeatStatus.ACTIVE),
            cards=tuple(parse_card_text(c) for c in rs.cards),
            is_button=rs.is_button,
            is_hero=rs.is_hero or (hero_name is not None and rs.name == hero_name),
        ))

    hero = next((s for s in seats if s.is_hero), None)
    if hero is None:
        raise ValueError("hero seat not found in observation (set is_hero or hero_name)")
    button = next((s.seat_id for s in seats if s.is_button), hero.seat_id)
    board = [parse_card_text(c) for c in raw.board]
    in_hand = [s for s in seats if s.status in (SeatStatus.ACTIVE, SeatStatus.ALL_IN)]
    max_committed = max((s.committed for s in in_hand), default=Decimal("0"))
    to_call = max(Decimal("0"), max_committed - hero.committed)
    # PokerNow's pot element shows the collected pot; add uncalled current-street bets.
    pot = parse_money(raw.pot) + sum((s.committed for s in in_hand), Decimal("0"))

    return GameState(
        config=TableConfig(small_blind=small_blind, big_blind=big_blind, max_seats=len(seats)),
        seats=tuple(seats), board=tuple(board),
        street=_STREET_BY_BOARD.get(len(board), Street.PREFLOP),
        button_seat_id=button, hero_seat_id=hero.seat_id,
        pot=pot, to_call=to_call, min_raise=big_blind, actions=tuple(actions),
    )


class Scraper:
    """DOM-reading layer (calibrate selectors via tools/selector_probe.py).

    These methods read the live page; they are not unit-tested (they need a real table),
    but they only feed the tested `to_game_state` core above.
    """

    def __init__(self, page, selectors, hero_name: str | None = None) -> None:
        self.page = page
        self.sel = selectors
        self.hero_name = hero_name

    def is_hero_turn(self) -> bool:
        """True when our action buttons are present/enabled."""
        area = self.page.query_selector(self.sel.action_area)
        if not area:
            return False
        return any(b.is_enabled() for b in area.query_selector_all("button"))

    def read_observation(self) -> RawObservation:
        seats: list[RawSeat] = []
        for i, el in enumerate(self.page.query_selector_all(self.sel.seat)):
            name_el = el.query_selector(self.sel.seat_name)
            stack_el = el.query_selector(self.sel.seat_stack)
            bet_el = el.query_selector(self.sel.seat_bet)
            classes = (el.get_attribute("class") or "")
            cards = [c.inner_text() for c in el.query_selector_all(".card") if c.inner_text().strip()]
            seats.append(RawSeat(
                seat_id=i,
                name=name_el.inner_text().strip() if name_el else None,
                stack=stack_el.inner_text() if stack_el else "0",
                bet=bet_el.inner_text() if bet_el else "",
                status="folded" if "fold" in classes else ("away" if "away" in classes else "active"),
                is_button=bool(el.query_selector(self.sel.dealer_button)) or "dealer" in classes,
                is_hero="you-player" in classes,
                cards=cards,
            ))
        board = [c.inner_text() for c in self.page.query_selector_all(self.sel.board_card)]
        pot_el = self.page.query_selector(self.sel.pot)
        return RawObservation(seats=seats, board=[b for b in board if b.strip()],
                              pot=pot_el.inner_text() if pot_el else "0")
