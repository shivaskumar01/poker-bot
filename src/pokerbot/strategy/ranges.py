"""Parameterized preflop ranges via percentile thresholds.

Rather than hand-encode 169-combo grids for every spot, we rank all hands once by a
playability score (heads-up equity + suited/connected/pair bonuses) and express each
situation as "play the strongest X%". X is a function of position / table size (via the
number of players left to act), stack depth, and the action faced. Constants are tuned for
a sound TAG baseline and are meant to be adjusted; the exploit layer deviates from here.
"""
from __future__ import annotations

from .notation import all_hand_classes, gap, is_pair, is_suited
from .preflop_strength import PREFLOP_EQUITY

# --- playability score & ranking (built once at import; pure arithmetic) ---
# Pairs get a large bonus because raw heads-up equity ignores their set-mining / made-hand
# value postflop (so every pair opens on the button, but small pairs still fold UTG).
PAIR_BONUS = 0.050
SUITED_BONUS = 0.035
CONNECTOR_BONUS = {0: 0.030, 1: 0.018, 2: 0.008}  # by gap (0 = connector)


def playability_score(cls: str) -> float:
    s = PREFLOP_EQUITY[cls]
    if is_pair(cls):
        return s + PAIR_BONUS
    if is_suited(cls):
        s += SUITED_BONUS
    return s + CONNECTOR_BONUS.get(gap(cls), 0.0)


_RANKED: list[str] = sorted(all_hand_classes(), key=playability_score, reverse=True)
_PCT: dict[str, float] = {c: (i + 1) / len(_RANKED) for i, c in enumerate(_RANKED)}
NUM_CLASSES = len(_RANKED)


def hand_percentile(cls: str) -> float:
    """Position of a class in the strength ranking, in (0, 1]; ~0.006 = AA, 1.0 = 32o."""
    return _PCT[cls]


def in_top(cls: str, fraction: float) -> bool:
    return _PCT[cls] <= fraction


# --- open-raise first-in ---
RFI_BY_LEFT = {2: 0.48, 3: 0.30, 4: 0.24, 5: 0.20, 6: 0.165, 7: 0.14, 8: 0.12, 9: 0.11}


def rfi_fraction(players_left: int, *, is_sb: bool, heads_up_match: bool,
                 blind_vs_blind: bool) -> float:
    if heads_up_match:
        return 0.85          # button in a true 2-handed match (in position vs the BB)
    if blind_vs_blind:
        return 0.60          # folded to the SB: SB vs BB, out of position
    if is_sb:
        return 0.42
    return RFI_BY_LEFT.get(max(2, min(players_left, 9)), 0.11)


def iso_fraction(players_left: int, num_limpers: int, *, is_sb: bool,
                 heads_up_match: bool, blind_vs_blind: bool) -> float:
    """Isolation-raise range over limpers — a touch tighter, value-weighted."""
    base = rfi_fraction(players_left, is_sb=is_sb, heads_up_match=heads_up_match,
                        blind_vs_blind=blind_vs_blind)
    return base * 0.80


# --- facing a single raise: (3bet-value fraction, continue fraction) ---
def vs_raise_thresholds(*, in_position: bool, players_left_behind: int,
                        vs_late_open: bool, is_bb: bool) -> tuple[float, float]:
    if is_bb:
        cont = 0.42 if vs_late_open else 0.27
        tb = 0.060 if vs_late_open else 0.045
    else:
        cont = 0.20 if in_position else 0.135
        tb = 0.060 if in_position else 0.050
        if vs_late_open:
            cont *= 1.4
            tb *= 1.5
    cont *= 0.9 ** max(0, players_left_behind)  # squeeze risk: tighten with players behind
    return tb, max(tb, cont)


# --- facing a 3-bet: (4bet-value fraction, continue fraction) ---
def vs_3bet_thresholds(*, in_position: bool) -> tuple[float, float]:
    fourbet = 0.025 if in_position else 0.020
    cont = 0.075 if in_position else 0.055
    return fourbet, max(fourbet, cont)


# --- short-stack push/fold ---
PUSH_BY_LEFT = {1: 0.62, 2: 0.50, 3: 0.36, 4: 0.30, 5: 0.25, 6: 0.21, 7: 0.18, 8: 0.16, 9: 0.14}


def push_fraction(players_left: int, eff_bb: float, *, is_sb: bool,
                  lone_opponent: bool) -> float:
    if lone_opponent:
        base = 0.70
    elif is_sb:
        base = 0.55
    else:
        base = PUSH_BY_LEFT.get(max(1, min(players_left, 9)), 0.14)
    if eff_bb <= 4:
        base *= 1.6
    elif eff_bb <= 7:
        base *= 1.25
    return min(base, 1.0)


def call_allin_fraction(eff_bb: float, *, in_position: bool) -> float:
    base = 0.16 if in_position else 0.13
    if eff_bb <= 6:
        base *= 1.4
    return min(base, 1.0)
