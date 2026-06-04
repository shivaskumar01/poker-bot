"""Parser for PokerNow exported game logs (the `poker_now_log_*.csv` format).

Rows are `entry,at,order`, newest-first; we sort by `order` ascending to replay. Players
carry a stable `@id` (display names can change case/spelling, the id does not), so we key on
id. This same structured output feeds both the opponent-stats accumulator and (later) the
live action-log scraper.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal

from ..model.cards import Card

_SUIT = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}  # ♠♥♦♣


def parse_glyph_card(token: str) -> Card:
    token = token.strip()
    suit = _SUIT[token[-1]]
    rank = token[:-1]
    if rank == "10":
        rank = "T"
    return Card(rank.upper(), suit)


def _split_player(s: str) -> tuple[str, str]:
    """'Arnav Shah @ l-gWRaVO5B' -> ('Arnav Shah', 'l-gWRaVO5B')."""
    name, _, pid = s.rpartition(" @ ")
    return name, pid


@dataclass
class ParsedAction:
    pid: str
    name: str
    kind: str          # sb|bb|post|raise|bet|call|check|fold
    amount: Decimal
    street: str        # preflop|flop|turn|river
    all_in: bool = False


@dataclass
class ParsedHand:
    number: int = 0
    dealer_id: str | None = None
    names: dict[str, str] = field(default_factory=dict)     # pid -> display name
    seats: dict[int, str] = field(default_factory=dict)     # seat number -> pid
    stacks: dict[str, Decimal] = field(default_factory=dict)  # pid -> starting stack
    hero_cards: list[Card] = field(default_factory=list)
    actions: list[ParsedAction] = field(default_factory=list)
    board: list[Card] = field(default_factory=list)
    shows: dict[str, list[Card]] = field(default_factory=dict)   # pid -> shown cards
    winners: dict[str, Decimal] = field(default_factory=dict)    # pid -> amount collected


_RE = {
    "start": re.compile(r"-- starting hand #(\d+).*\(dealer: \"(.*?)\"\)"),
    "stacks": re.compile(r"Player stacks: (.+)$"),
    "stack_item": re.compile(r"#(\d+) \"(.*?)\" \(([\d.]+)\)"),
    "hand": re.compile(r"Your hand is (.+)$"),
    "missed": re.compile(r"\"(.*?)\" posts a miss(?:ed|ing) (?:big|small) blind of ([\d.]+)"),
    "sb": re.compile(r"\"(.*?)\" posts a small blind of ([\d.]+)"),
    "bb": re.compile(r"\"(.*?)\" posts a big blind of ([\d.]+)"),
    "raise": re.compile(r"\"(.*?)\" raises to ([\d.]+)"),
    "bet": re.compile(r"\"(.*?)\" bets ([\d.]+)"),
    "call": re.compile(r"\"(.*?)\" calls ([\d.]+)"),
    "check": re.compile(r"\"(.*?)\" checks"),
    "fold": re.compile(r"\"(.*?)\" folds"),
    "show": re.compile(r"\"(.*?)\" shows a (.+?)\."),
    "collect": re.compile(r"\"(.*?)\" collected ([\d.]+) from pot"),
}
# verbs that carry an amount, in priority order (missed before the plain blinds)
_AMOUNT_KINDS = ["missed", "sb", "bb", "raise", "bet", "call"]
_KIND_NAME = {"missed": "post", "sb": "sb", "bb": "bb", "raise": "raise", "bet": "bet", "call": "call"}


def _bracket(entry: str) -> list[Card]:
    inside = entry[entry.find("[") + 1: entry.find("]")]
    return [parse_glyph_card(c) for c in inside.split(",") if c.strip()]


def parse_file(path: str) -> list[ParsedHand]:
    rows: list[tuple[int, str]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for row in reader:
            if len(row) < 3:
                continue
            try:
                rows.append((int(row[2]), row[0]))
            except ValueError:
                continue
    rows.sort(key=lambda r: r[0])

    hands: list[ParsedHand] = []
    cur: ParsedHand | None = None
    street = "preflop"

    for _order, entry in rows:
        m = _RE["start"].search(entry)
        if m:
            cur = ParsedHand(number=int(m.group(1)))
            cur.dealer_id = _split_player(m.group(2))[1]
            street = "preflop"
            hands.append(cur)
            continue
        if cur is None:
            continue
        if entry.startswith("-- ending hand"):
            cur = None
            continue

        low = entry.lower()
        if low.startswith("flop"):
            street = "flop"
            cur.board = _bracket(entry)
            continue
        if low.startswith("turn"):
            street = "turn"
            cur.board += _bracket(entry)
            continue
        if low.startswith("river"):
            street = "river"
            cur.board += _bracket(entry)
            continue

        m = _RE["stacks"].search(entry)
        if m:
            for seat, nm, stk in _RE["stack_item"].findall(m.group(1)):
                name, pid = _split_player(nm)
                cur.seats[int(seat)] = pid
                cur.stacks[pid] = Decimal(stk)
                cur.names[pid] = name
            continue
        m = _RE["hand"].search(entry)
        if m:
            cur.hero_cards = [parse_glyph_card(c) for c in m.group(1).split(",")]
            continue

        matched = False
        for key in _AMOUNT_KINDS:
            m = _RE[key].search(entry)
            if m:
                name, pid = _split_player(m.group(1))
                cur.names.setdefault(pid, name)
                cur.actions.append(ParsedAction(pid, name, _KIND_NAME[key], Decimal(m.group(2)),
                                                street, " all in" in entry))
                matched = True
                break
        if matched:
            continue
        for key in ("check", "fold"):
            m = _RE[key].search(entry)
            if m:
                name, pid = _split_player(m.group(1))
                cur.names.setdefault(pid, name)
                cur.actions.append(ParsedAction(pid, name, key, Decimal("0"), street))
                matched = True
                break
        if matched:
            continue
        m = _RE["show"].search(entry)
        if m:
            _name, pid = _split_player(m.group(1))
            for tok in m.group(2).split(","):      # "shows a 9♦." or "shows a J♥, K♦."
                tok = tok.strip()
                if not tok:
                    continue
                try:
                    cur.shows.setdefault(pid, []).append(parse_glyph_card(tok))
                except (KeyError, IndexError):
                    pass
            continue
        m = _RE["collect"].search(entry)
        if m:
            _name, pid = _split_player(m.group(1))
            cur.winners[pid] = cur.winners.get(pid, Decimal("0")) + Decimal(m.group(2))
            continue

    return hands
