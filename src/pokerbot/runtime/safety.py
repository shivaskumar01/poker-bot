"""Session safety: stop-loss / stop-win / hand cap / kill switch.

(Think-time pacing lives in strategy/timing.think_seconds, applied by the orchestrator.)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Limits:
    stop_loss_bb: float
    stop_win_bb: float
    max_hands: int


class SessionGuard:
    def __init__(self, limits: Limits, big_blind, kill_file: str = "STOP") -> None:
        self.limits = limits
        self.bb = Decimal(str(big_blind))
        self.kill_file = kill_file
        self.start: Decimal | None = None
        self.current: Decimal | None = None
        self.hands = 0

    def observe_bankroll(self, stack: Decimal) -> None:
        """Record hero's between-hands stack; the first call anchors the session baseline."""
        if self.start is None:
            self.start = stack
        self.current = stack

    def count_hand(self) -> None:
        self.hands += 1

    def reset_baseline(self, stack: Decimal) -> None:
        """Re-anchor the bankroll baseline (e.g. after a re-buy) so stop-loss measures fresh."""
        self.start = stack
        self.current = stack

    @property
    def net_bb(self) -> float:
        if self.start is None or self.current is None or self.bb <= 0:
            return 0.0
        return float((self.current - self.start) / self.bb)

    def kill_requested(self) -> bool:
        return bool(self.kill_file) and os.path.exists(self.kill_file)

    def should_stop(self) -> tuple[bool, str]:
        if self.kill_requested():
            return True, f"kill switch ('{self.kill_file}' file present)"
        if self.hands >= self.limits.max_hands:
            return True, f"max hands reached ({self.limits.max_hands})"
        if self.net_bb <= -self.limits.stop_loss_bb:
            return True, f"stop-loss hit ({self.net_bb:+.0f}bb)"
        if self.net_bb >= self.limits.stop_win_bb:
            return True, f"stop-win hit ({self.net_bb:+.0f}bb)"
        return False, ""
