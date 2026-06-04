"""Randomized / mixed-strategy selection.

Poker requires realizing frequencies (e.g. "3-bet this combo 35% of the time"), not
deterministic play. The Mixer wraps an RNG so decisions are reproducible under a seed
(critical for self-play tests).
"""
from __future__ import annotations

import random


class Mixer:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random

    def chance(self, p: float) -> bool:
        """True with probability p (clamped to [0, 1])."""
        if p <= 0.0:
            return False
        if p >= 1.0:
            return True
        return self.rng.random() < p

    def choose(self, options: list[tuple]) -> object:
        """Pick a value from [(value, weight), ...] proportional to weight."""
        total = sum(w for _, w in options)
        if total <= 0:
            raise ValueError("weights must sum to a positive number")
        r = self.rng.random() * total
        upto = 0.0
        for value, w in options:
            upto += w
            if r <= upto:
                return value
        return options[-1][0]
