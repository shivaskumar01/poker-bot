"""Thin wrapper over eval7 (fast C hand evaluator).

eval7.evaluate(cards) returns an int strength (higher is better) for any 5-7 card list.
We keep a single shared table of eval7.Card objects keyed by our string form so the hot
Monte-Carlo loop never re-parses card strings.
"""
from __future__ import annotations

import eval7

from ..model.cards import ALL_CARD_STRINGS, Card

# Single source of truth for eval7.Card objects (shared with montecarlo).
_E: dict[str, eval7.Card] = {s: eval7.Card(s) for s in ALL_CARD_STRINGS}


def to_eval7(card: Card) -> eval7.Card:
    return _E[str(card)]


def evaluate(cards: list[Card]) -> int:
    """Strength of the best 5-card hand from 5-7 cards (higher wins)."""
    return eval7.evaluate([_E[str(c)] for c in cards])


def hand_category(cards: list[Card]) -> str:
    """Human-readable category, e.g. 'Full House', 'Flush', 'Straight Flush'."""
    return eval7.handtype(eval7.evaluate([_E[str(c)] for c in cards]))
