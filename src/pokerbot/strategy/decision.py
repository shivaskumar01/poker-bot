"""The output of the decision engine."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..model.state import ActionType


@dataclass(frozen=True, slots=True)
class Decision:
    action: ActionType
    amount: Decimal           # for BET/RAISE: the total "raise-to" this street; else 0 / to_call
    rationale: str            # one-line human explanation (logged for review)
    equity: float | None = None
    confidence: float = 1.0   # 1.0 = pure; <1.0 = a mixed/borderline spot
