"""Multiway Monte-Carlo equity.

Estimate hero's pot equity against N opponents by repeatedly dealing the opponents random
hole cards and completing the board, then comparing best hands. Ties split fractionally.
Opponents are modeled as uniformly random hands for now; explicit per-opponent ranges will
be layered in with the strategy engine (the sampling hook is `dead_cards`).
"""
from __future__ import annotations

import random

import eval7

from ..model.cards import ALL_CARD_STRINGS, Card
from .evaluator import _E


def equity(
    hero: list[Card],
    board: list[Card],
    num_opponents: int,
    iterations: int = 20_000,
    dead_cards: list[Card] | None = None,
    rng: random.Random | None = None,
) -> float:
    """Hero's share of the pot in [0, 1] vs `num_opponents` random hands.

    `dead_cards` are cards known to be unavailable (e.g. folded/exposed) and removed from
    the sampling deck. A tie among k players returns 1/k to hero.
    """
    if len(hero) != 2:
        raise ValueError("hero must have exactly 2 cards")
    if not 0 <= len(board) <= 5:
        raise ValueError("board must be 0..5 cards")
    if num_opponents < 1:
        raise ValueError("need at least one opponent")

    rng = rng or random
    used = {str(c) for c in hero} | {str(c) for c in board}
    if dead_cards:
        used |= {str(c) for c in dead_cards}

    hero_e = [_E[str(c)] for c in hero]
    board_e = [_E[str(c)] for c in board]
    deck = [_E[s] for s in ALL_CARD_STRINGS if s not in used]

    need = 5 - len(board_e)
    draw = num_opponents * 2 + need
    if draw > len(deck):
        raise ValueError("not enough cards in the deck for this many opponents")

    ev = eval7.evaluate
    sample = rng.sample
    wins = ties = 0.0

    for _ in range(iterations):
        s = sample(deck, draw)
        full_board = board_e + s[:need]
        hero_score = ev(hero_e + full_board)

        opp_best = -1
        idx = need
        for _o in range(num_opponents):
            score = ev([s[idx], s[idx + 1]] + full_board)
            if score > opp_best:
                opp_best = score
            idx += 2

        if hero_score > opp_best:
            wins += 1.0
        elif hero_score == opp_best:
            tied = 1  # hero
            idx = need
            for _o in range(num_opponents):
                if ev([s[idx], s[idx + 1]] + full_board) == opp_best:
                    tied += 1
                idx += 2
            ties += 1.0 / tied

    return (wins + ties) / iterations


def recommended_iterations(pot_bb: float, base: int = 20_000, big: int = 60_000) -> int:
    """More rollouts when the decision is for a big pot (lower variance where it matters)."""
    return big if pot_bb >= 40 else base
