"""169-class preflop hand notation ("AA", "AKs", "72o") and helpers.

Specific suits are irrelevant to preflop strength by symmetry, so every starting hand
collapses to one of 169 classes (13 pairs + 78 suited + 78 offsuit).
"""
from __future__ import annotations

from ..model.cards import Card

RANKS_DESC = "AKQJT98765432"  # index 0 = Ace (strongest)
_IDX = {r: i for i, r in enumerate(RANKS_DESC)}


def canonical(c1: Card, c2: Card) -> str:
    """Two concrete cards -> canonical class, higher rank first ('AKs', 'QQ', '72o')."""
    a, b = c1, c2
    if _IDX[a.rank] > _IDX[b.rank]:
        a, b = b, a  # ensure a is the higher rank
    if a.rank == b.rank:
        return a.rank + b.rank
    return a.rank + b.rank + ("s" if a.suit == b.suit else "o")


def all_hand_classes() -> list[str]:
    """All 169 classes (suited = upper triangle, offsuit = lower, pairs = diagonal)."""
    out: list[str] = []
    for i in range(13):
        for j in range(13):
            if i == j:
                out.append(RANKS_DESC[i] * 2)
            elif i < j:
                out.append(RANKS_DESC[i] + RANKS_DESC[j] + "s")
            else:
                out.append(RANKS_DESC[j] + RANKS_DESC[i] + "o")
    return out


def is_pair(cls: str) -> bool:
    return len(cls) == 2


def is_suited(cls: str) -> bool:
    return cls.endswith("s")


def gap(cls: str) -> int:
    """Rank distance between the two cards (0 = connector like 76s/AKs; pairs -> 0)."""
    if is_pair(cls):
        return 0
    return abs(_IDX[cls[0]] - _IDX[cls[1]]) - 1


def representative_cards(cls: str) -> list[Card]:
    """Concrete cards for one class (for equity calc); suit choice is arbitrary."""
    if is_pair(cls):
        r = cls[0]
        return [Card(r, "s"), Card(r, "h")]
    r1, r2 = cls[0], cls[1]
    if is_suited(cls):
        return [Card(r1, "s"), Card(r2, "s")]
    return [Card(r1, "s"), Card(r2, "h")]
