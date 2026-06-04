"""Framework-agnostic card model.

Internal cards are plain (rank, suit) values rendered as two-char strings ("As", "Td",
"9h"). The equity layer converts these to eval7.Card objects for fast evaluation; keeping
our own type means the rest of the codebase never depends on a specific poker library.
"""
from __future__ import annotations

from dataclasses import dataclass

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}  # '2'->2 ... 'A'->14


@dataclass(frozen=True, slots=True)
class Card:
    rank: str  # one of RANKS
    suit: str  # one of SUITS

    def __post_init__(self) -> None:
        if self.rank not in RANKS:
            raise ValueError(f"invalid rank: {self.rank!r}")
        if self.suit not in SUITS:
            raise ValueError(f"invalid suit: {self.suit!r}")

    def __str__(self) -> str:
        return f"{self.rank}{self.suit}"

    @property
    def value(self) -> int:
        return RANK_VALUE[self.rank]

    @classmethod
    def parse(cls, token: str) -> "Card":
        token = token.strip()
        # accept "10h" as well as "Th"
        if len(token) == 3 and token[:2] == "10":
            return cls("T", token[2].lower())
        if len(token) != 2:
            raise ValueError(f"cannot parse card: {token!r}")
        return cls(token[0].upper(), token[1].lower())


def parse_cards(text: str) -> list[Card]:
    """Parse "AsKd" or "As Kd" or "As,Kd" into a list of Cards."""
    text = text.replace(",", " ").strip()
    if " " in text:
        tokens = text.split()
    else:
        # tightly packed: split every 2 chars (no "10" support in packed form; use "T")
        tokens = [text[i : i + 2] for i in range(0, len(text), 2)]
    return [Card.parse(t) for t in tokens]


ALL_CARD_STRINGS: list[str] = [r + s for r in RANKS for s in SUITS]


def full_deck() -> list[Card]:
    return [Card(r, s) for r in RANKS for s in SUITS]
