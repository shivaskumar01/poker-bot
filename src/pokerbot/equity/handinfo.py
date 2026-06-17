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


def _flush_draw(hole, board) -> bool:
    if len(board) >= 5:
        return False
    counts = Counter(c.suit for c in list(hole) + list(board))
    if not counts:
        return False
    suit, n = max(counts.items(), key=lambda kv: kv[1])
    return n == 4 and any(c.suit == suit for c in hole)     # HERO must hold one of the suit


def _straight_draw(hole, board) -> bool:
    """Open-ended straight draw only (four in a row, completable on BOTH ends) that USES a hole card
, a draw sitting entirely on the board isn't the hero's. Gutshots/one-enders are too weak."""
    if len(board) >= 5:
        return False
    vals = {c.value for c in list(hole) + list(board)}
    hole_vals = {c.value for c in hole}
    if 14 in vals:
        vals.add(1)          # wheel ace
    if 14 in hole_vals:
        hole_vals.add(1)
    for low in range(2, 11):                        # runs 2-5 .. 10-13: both ends make a straight
        run = set(range(low, low + 4))
        if run <= vals and (run & hole_vals):       # the run includes a hole card
            return True
    return False


def classify_hand(hole: tuple[Card, ...], board: tuple[Card, ...]) -> HandInfo:
    all_cards = list(hole) + list(board)
    if len(hole) < 2 or len(all_cards) < 5:         # cards not (fully) read -> treat as air, never crash
        return HandInfo(category="High Card", made=False, strong=False, draw=False)
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

    draw = _flush_draw(hole, board) or _straight_draw(hole, board)
    return HandInfo(category=cat, made=made, strong=strong, draw=draw)
