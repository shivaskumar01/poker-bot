"""Classify a villain into an archetype from their (shrunk) stats.

Labels: nit (tight), tag (tight-aggressive), lag (loose-aggressive), station
(loose-passive, pays off), maniac (hyper-aggressive), or unknown (too few hands).
"""
from __future__ import annotations

from .stats import PlayerStats


def classify(ps: PlayerStats) -> str:
    if ps.hands < 15:
        return "unknown"
    vpip = ps.r("vpip")
    pfr = ps.r("pfr")
    af = ps.af
    aggression_ratio = (pfr / vpip) if vpip > 0 else 0.0

    if vpip < 0.15:
        return "nit"
    if af > 4.0 and vpip > 0.30:
        return "maniac"
    if vpip >= 0.30 and aggression_ratio < 0.5 and af < 1.8:
        return "station"
    if vpip > 0.27 and pfr > 0.19 and af >= 2.0:
        return "lag"
    return "tag"
