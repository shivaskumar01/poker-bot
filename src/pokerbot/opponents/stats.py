"""Per-opponent HUD statistics with confidence shrinkage.

Each rate stat is a (made, opportunities) counter. Reading a rate off a tiny sample lies
(see the project's eval-hygiene rule), so every rate is shrunk toward a population baseline
with a pseudo-count: small samples read close to "average", and only converge to the
observed rate as opportunities accumulate. `confidence` (0..1) scales how hard the exploit
layer is allowed to deviate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CONF_FULL_HANDS = 60  # hands observed at which confidence saturates to 1.0

# Population baselines (~6-max regular). Small samples are pulled toward these.
BASELINE: dict[str, float] = {
    "vpip": 0.24,
    "pfr": 0.18,
    "threebet": 0.07,
    "fold_to_3bet": 0.55,
    "cbet_flop": 0.55,
    "fold_to_cbet_flop": 0.45,
    "wtsd": 0.27,
}
SHRINK_WEIGHT = 20      # pseudo-opportunities of baseline mixed into every rate
AF_BASELINE = 2.5       # baseline aggression factor (bets+raises)/calls
AF_WEIGHT = 5


@dataclass
class Stat:
    made: int = 0
    opp: int = 0

    def observe(self, made: bool) -> None:
        self.opp += 1
        if made:
            self.made += 1

    @property
    def raw(self) -> float | None:
        return self.made / self.opp if self.opp else None

    def shrunk(self, prior: float, weight: int = SHRINK_WEIGHT) -> float:
        return (self.made + prior * weight) / (self.opp + weight)


@dataclass
class PlayerStats:
    name: str
    hands: int = 0
    vpip: Stat = field(default_factory=Stat)
    pfr: Stat = field(default_factory=Stat)
    threebet: Stat = field(default_factory=Stat)
    fold_to_3bet: Stat = field(default_factory=Stat)
    cbet_flop: Stat = field(default_factory=Stat)
    fold_to_cbet_flop: Stat = field(default_factory=Stat)
    wtsd: Stat = field(default_factory=Stat)
    agg_actions: int = 0   # postflop bets + raises
    call_actions: int = 0  # postflop calls

    def r(self, name: str) -> float:
        """Shrunk rate for a named stat (e.g. 'vpip', 'fold_to_cbet_flop')."""
        return getattr(self, name).shrunk(BASELINE[name])

    @property
    def af(self) -> float:
        return (self.agg_actions + AF_BASELINE * AF_WEIGHT) / (self.call_actions + AF_WEIGHT)

    @property
    def confidence(self) -> float:
        return min(1.0, self.hands / CONF_FULL_HANDS)
