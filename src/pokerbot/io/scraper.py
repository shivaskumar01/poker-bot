"""Scrape PokerNow's DOM into a GameState.

Pure assembly core (`to_game_state`, fully unit-tested) + a thin Playwright reading layer
(`Scraper`, calibrated live). Cards are decoded from `.card-container` classes; to-call is
read from the action buttons; the dealer seat from `.dealer-position-N`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from decimal import Decimal

from ..model.cards import Card
from ..model.state import IN_HAND, GameState, Seat, SeatStatus, Street, TableConfig

_STATUS_MAP = {
    "active": SeatStatus.ACTIVE, "folded": SeatStatus.FOLDED, "all_in": SeatStatus.ALL_IN,
    "allin": SeatStatus.ALL_IN, "sitting_out": SeatStatus.SITTING_OUT,
    "away": SeatStatus.AWAY, "empty": SeatStatus.EMPTY,
}
_STREET_BY_BOARD = {0: Street.PREFLOP, 3: Street.FLOP, 4: Street.TURN, 5: Street.RIVER}
_MONEY_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*([KkMm])?")
_SUIT_CLASS = re.compile(r"card-([shdc])(?![\w-])")          # card-s / card-h / ... (not card-s-7)
_RANK_CLASS = re.compile(r"card-s-(10|[2-9TJQKA])", re.I)    # card-s-7, card-s-K, card-s-10


def parse_money(s: str) -> Decimal:
    r"""First numeric amount from messy text ('0\n\ntotal 0', '1,234.50', '1.2K', '$25')."""
    m = _MONEY_RE.search(s.replace("$", "").replace("€", "").replace("£", ""))
    if not m:
        return Decimal("0")
    value = Decimal(m.group(1).replace(",", ""))
    if m.group(2):
        value *= {"k": 1000, "m": 1_000_000}[m.group(2).lower()]
    return value


_BLINDS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")


def parse_blinds_text(text: str):
    """Pull a small/big-blind pair out of text like 'NLH 0.25/0.50'. Returns (sb, bb) or None.
    Filters to plausible blinds (sb <= bb <= 3*sb) and prefers the smallest such pair."""
    clean = (text or "").translate({ord(c): None for c in "$€£₹"})   # tolerate currency symbols
    cands = []
    for a, b in _BLINDS_RE.findall(clean):
        try:
            sa, sb = Decimal(a), Decimal(b)
        except Exception:
            continue
        if 0 < sa <= sb <= sa * 3:
            cands.append((sa, sb))
    return min(cands, key=lambda p: p[1]) if cands else None


def parse_card_text(s: str) -> Card:
    s = s.strip().replace("\n", "").replace(" ", "")
    glyph = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}
    suit = glyph.get(s[-1], s[-1].lower())
    rank = s[:-1]
    if rank == "10":
        rank = "T"
    return Card(rank.upper(), suit)


def card_from_classes(class_str: str) -> Card | None:
    """Decode a `.card-container` class string, e.g. 'card-container card-d card-s-6 flipped'."""
    sm = _SUIT_CLASS.search(class_str)
    rm = _RANK_CLASS.search(class_str)
    if not (sm and rm):
        return None
    rank = rm.group(1).upper()
    if rank == "10":
        rank = "T"
    return Card(rank, sm.group(1))


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
    to_call: str | None = None          # if set (e.g. read from buttons), used verbatim
    button_seat_id: int | None = None   # if set (from .dealer-position-N), used verbatim


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
    if raw.button_seat_id is not None:
        button = raw.button_seat_id
    else:
        button = next((s.seat_id for s in seats if s.is_button), hero.seat_id)
    board = [parse_card_text(c) for c in raw.board]
    in_hand = [s for s in seats if s.status in (SeatStatus.ACTIVE, SeatStatus.ALL_IN)]
    if raw.to_call is not None:
        to_call = parse_money(raw.to_call)
    else:
        max_committed = max((s.committed for s in in_hand), default=Decimal("0"))
        to_call = max(Decimal("0"), max_committed - hero.committed)
    pot = parse_money(raw.pot) + sum((s.committed for s in in_hand), Decimal("0"))

    return GameState(
        config=TableConfig(small_blind=small_blind, big_blind=big_blind, max_seats=len(seats)),
        seats=tuple(seats), board=tuple(board),
        street=_STREET_BY_BOARD.get(len(board), Street.PREFLOP),
        button_seat_id=button, hero_seat_id=hero.seat_id,
        pot=pot, to_call=to_call, min_raise=big_blind, actions=tuple(actions),
    )


def reconstruct_preflop(gs: GameState, small_blind: Decimal, big_blind: Decimal) -> GameState:
    """Rebuild preflop committed amounts + pot from blinds and the amount-to-call.

    PokerNow shows 0 in the pot display preflop (bets sit in front of players) and the live
    scraper can't read per-seat bet chips — so without this, pot=0 and pot-odds blow up,
    making the bot fold everything to a 3-bet. Heads-up-accurate; multiway approximate.
    """
    if gs.street != Street.PREFLOP:
        return gs
    pos = gs.positions
    hero_blind = big_blind if pos.get(gs.hero_seat_id) == "BB" else small_blind
    lone = gs.live_opponents[0].seat_id if len(gs.live_opponents) == 1 else None

    seats = []
    for s in gs.seats:
        if s.status not in IN_HAND:
            seats.append(s)
            continue
        if s.seat_id == gs.hero_seat_id:
            committed = hero_blind
        elif gs.to_call > 0 and s.seat_id == lone:
            committed = hero_blind + gs.to_call          # the heads-up raiser's total
        else:
            p = pos.get(s.seat_id)
            committed = big_blind if p == "BB" else (small_blind if p == "SB" else Decimal("0"))
        seats.append(replace(s, committed=committed, total_committed=committed))

    pot = sum((x.committed for x in seats if x.status in IN_HAND), Decimal("0"))
    return replace(gs, seats=tuple(seats), pot=pot)


class Scraper:
    """DOM-reading layer (calibrated selectors). Feeds the tested `to_game_state` core."""

    def __init__(self, page, selectors, hero_name: str | None = None) -> None:
        self.page = page
        self.sel = selectors
        self.hero_name = hero_name

    def action_buttons_present(self) -> bool:
        """Any fold/check/call/raise control is on screen — but this ALSO matches the pre-action
        controls PokerNow shows during the OPPONENT's turn, so it is NOT 'is it my turn'."""
        return any(self.page.query_selector(s) for s in
                   (self.sel.btn_fold, self.sel.btn_check, self.sel.btn_call, self.sel.btn_raise))

    def is_hero_turn(self) -> bool:
        """CHEAP + reliable: it's the hero's turn iff the hero's seat is the CURRENT ACTOR — the
        seat with `.decision-current`. During the opponent's turn THEIR seat carries it and the hero
        only sees pre-action ('Check/Fold ahead') controls, so this single class check (no per-loop
        button scan or inner_text read) is all that's needed and keeps the poll loop light. The bot
        therefore does NO hand work until it's genuinely its turn."""
        return self.page.query_selector(f".you-player.{self.sel.current_actor_class}") is not None

    def _to_call_text(self) -> str:
        # PokerNow labels the call-classed button "CALL <amt>" ONLY when facing a bet; when a
        # check is available it shows "BET <min>" (same 'call' class) next to a check button.
        # So we read the button TEXT, not just its presence.
        call_btn = self.page.query_selector(self.sel.btn_call)
        if call_btn:
            text = call_btn.inner_text() or ""
            if "call" in text.lower():
                return text          # e.g. "CALL 2.00"
        return "0"                   # checkable, or only a min-bet shortcut -> nothing to call

    def read_observation(self) -> RawObservation:
        seats: list[RawSeat] = []
        for el in self.page.query_selector_all(self.sel.seat):
            classes = el.get_attribute("class") or ""
            name_el = el.query_selector(self.sel.seat_name)
            name = name_el.inner_text().strip() if name_el else None
            if not name:
                continue
            seat_match = re.search(r"table-player-(\d+)", classes)
            stack_el = el.query_selector(self.sel.seat_stack)
            is_hero = self.sel.hero_seat_class in classes or (
                self.hero_name is not None and name == self.hero_name)
            cards = []
            if is_hero:
                for cc in el.query_selector_all(".card-container.flipped"):
                    c = card_from_classes(cc.get_attribute("class") or "")
                    if c:
                        cards.append(str(c))
            if self.sel.folded_class in classes:
                status = "folded"
            elif "waiting" in classes or "away" in classes:
                status = "away"
            else:
                status = "active"
            seats.append(RawSeat(
                seat_id=int(seat_match.group(1)) if seat_match else len(seats),
                name=name, stack=stack_el.inner_text() if stack_el else "0",
                status=status, is_hero=is_hero, cards=cards,
            ))

        button_seat = None
        btn = self.page.query_selector(self.sel.dealer_button)
        if btn:
            dm = re.search(r"dealer-position-(\d+)", btn.get_attribute("class") or "")
            if dm:
                button_seat = int(dm.group(1))

        board = []
        for cc in self.page.query_selector_all(self.sel.board_card):
            c = card_from_classes(cc.get_attribute("class") or "")
            if c:
                board.append(str(c))

        pot_el = self.page.query_selector(self.sel.pot)
        return RawObservation(
            seats=seats, board=board, pot=pot_el.inner_text() if pot_el else "0",
            to_call=self._to_call_text(), button_seat_id=button_seat,
        )

    def read_blinds(self):
        """Best-effort live blinds (sb, bb) or None — checks blind-ish elements then the page."""
        for sel in (self.sel.blinds, "[class*='blind']", "[class*='stake']", "[class*='game-name']"):
            if not sel:
                continue
            try:
                for el in self.page.query_selector_all(sel):
                    found = parse_blinds_text(el.inner_text() or "")
                    if found:
                        return found
            except Exception:  # noqa: BLE001
                pass
        try:
            return parse_blinds_text(self.page.inner_text("body"))
        except Exception:  # noqa: BLE001
            return None

    def read_seconds_left(self):
        """Best-effort: seconds left on the hero's action timer (or None). Used so the bot acts
        before PokerNow auto-folds it. Calibrated loosely; the live DOM is dumped on the first turn
        so the exact timer selector can be confirmed."""
        sels = (".you-player [class*='time']", ".you-player [class*='timer']",
                ".you-player [class*='count']", ".decision-current [class*='time']",
                "[class*='action-timer']", "[class*='time-bank'] [class*='time']")
        for sel in sels:
            try:
                for el in self.page.query_selector_all(sel):
                    if not el.is_visible():
                        continue
                    m = re.search(r"(\d+(?:\.\d+)?)", el.inner_text() or "")
                    if m:
                        v = float(m.group(1))
                        if 0 <= v <= 600:
                            return v
            except Exception:  # noqa: BLE001
                pass
        return None

    def read_hero_stack(self):
        """Hero's current stack (Decimal) or None — used for live stop-loss + bust detection."""
        for el in self.page.query_selector_all(self.sel.seat):
            classes = el.get_attribute("class") or ""
            name_el = el.query_selector(self.sel.seat_name)
            name = name_el.inner_text().strip() if name_el else None
            if self.sel.hero_seat_class in classes or (self.hero_name and name == self.hero_name):
                st = el.query_selector(self.sel.seat_stack)
                return parse_money(st.inner_text()) if st else None
        return None
