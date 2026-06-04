"""Table-size-aware position model — the linchpin of dynamic adaptation.

Given the seats currently *in the hand* (in clockwise/seat order) and which seat holds the
button, assign each a position label on the 2-to-10-handed continuum, and produce preflop /
postflop action orders. PokerNow tables seat up to 10, so we cover N = 2..10.

Convention: labels are listed clockwise starting at the button:
    [BTN, SB, BB, UTG, ... , CO]
In heads-up the button posts the small blind, so seat 0 is BTN (acts first preflop, last
postflop) and seat 1 is BB.
"""
from __future__ import annotations

POSITION_LABELS: dict[int, list[str]] = {
    2: ["BTN", "BB"],  # BTN is also SB in heads-up
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "UTG"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "MP", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG1", "MP", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG1", "MP", "LJ", "HJ", "CO"],
    10: ["BTN", "SB", "BB", "UTG", "UTG1", "UTG2", "MP", "LJ", "HJ", "CO"],
}

# "Lateness" rank for strategy: higher = later position = wider range. BTN is latest.
LATENESS = {"UTG": 0, "UTG1": 1, "UTG2": 2, "MP": 3, "LJ": 4, "HJ": 5, "CO": 6, "BTN": 7,
            "SB": -1, "BB": -2}


def _rotate_to_button(seats_clockwise: list, button) -> list:
    seats = list(seats_clockwise)
    n = len(seats)
    if n not in POSITION_LABELS:
        raise ValueError(f"unsupported table size: {n} (must be 2..10)")
    if button not in seats:
        raise ValueError(f"button {button!r} not among seats {seats!r}")
    bi = seats.index(button)
    return seats[bi:] + seats[:bi]  # button first, then clockwise (SB, BB, ...)


def assign_positions(seats_clockwise: list, button) -> dict:
    """Map each in-hand seat id to its position label."""
    rotated = _rotate_to_button(seats_clockwise, button)
    labels = POSITION_LABELS[len(rotated)]
    return {seat: labels[i] for i, seat in enumerate(rotated)}


def preflop_action_order(seats_clockwise: list, button) -> list:
    """Seat ids in preflop action order (first to act = left of the big blind)."""
    rotated = _rotate_to_button(seats_clockwise, button)
    n = len(rotated)
    bb_index = 2 if n >= 3 else 1  # heads-up has no separate SB seat in the list
    start = (bb_index + 1) % n
    return rotated[start:] + rotated[:start]


def postflop_action_order(seats_clockwise: list, button) -> list:
    """Seat ids in postflop action order (first = SB / first live seat left of button;
    button always acts last)."""
    rotated = _rotate_to_button(seats_clockwise, button)
    return rotated[1:] + rotated[:1]
