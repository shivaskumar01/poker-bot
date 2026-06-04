"""Postflop hand reading: is hero's hand a made hand, a draw, or air?

This is what lets the bot stop "semi-bluffing" one pair on the river or barreling ace-high
with no draw. `made` = real showdown value (a pair using a hole card, or better). `strong` =
value-bet worthy (two pair+, top pair, or an overpair). `draw` = a flush or straight draw
with cards still to come (so it's never true on the river).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import eval7

from ..model.cards import Card
from .evaluator import _E

# eval7 category strings (verified): High Card, Pair, Two Pair, Trips, Straight, Flush,
# Full House, Quads, Straight Flush.
_STRONG_MADE = {"Two Pair", "Trips", "Straight", "Flush", "Full House", "Quads", "Straight Flush"}


@dataclass(frozen=True, slots=True)
class HandInfo:
    category: str
    made: bool      # real showdown value (pair+ involving a hole card, or better)
    strong: bool    # value-bet worthy
    draw: bool      # flush or straight draw, with cards to come


def _category(cards) -> str:
    return eval7.handtype(eval7.evaluate([_E[str(c)] for c in cards]))


def _flush_draw(cards, board_len: int) -> bool:
    if board_len >= 5:
        return False
    return max(Counter(c.suit for c in cards).values()) == 4


def _straight_draw(cards, board_len: int) -> bool:
    """Open-ended straight draw only (four in a row, completable on BOTH ends). Gutshots and
    one-enders (4 outs) are too weak to treat as a draw for (semi-)bluffing."""
    if board_len >= 5:
        return False
    vals = {c.value for c in cards}
    if 14 in vals:
        vals.add(1)  # wheel ace
    for low in range(2, 11):                        # runs 2-5 .. 10-13: both ends make a straight
        if set(range(low, low + 4)) <= vals:
            return True
    return False


def classify_hand(hole: tuple[Card, ...], board: tuple[Card, ...]) -> HandInfo:
    all_cards = list(hole) + list(board)
    cat = _category(all_cards)
    board_ranks = [c.value for c in board]
    top_board = max(board_ranks) if board_ranks else 0
    pocket_pair = hole[0].rank == hole[1].rank
    pairs_board = any(c.value in board_ranks for c in hole)

    made = cat in _STRONG_MADE or pocket_pair or pairs_board
    if cat in _STRONG_MADE:
        strong = True
    elif cat == "Pair" and pocket_pair and hole[0].value > top_board:
        strong = True                                   # overpair
    elif cat == "Pair" and pairs_board and any(c.value == top_board for c in hole):
        strong = True                                   # top pair
    else:
        strong = False                                  # weak/middle pair, or board pair only

    draw = _flush_draw(all_cards, len(board)) or _straight_draw(all_cards, len(board))
    return HandInfo(category=cat, made=made, strong=strong, draw=draw)
