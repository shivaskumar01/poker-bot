"""Single source of truth for PokerNow DOM selectors.

PokerNow's markup uses class names that can change, so these are **best-effort defaults**
to be confirmed/corrected by running `tools/selector_probe.py` against a live table. A DOM
change is then a one-file fix here. Action buttons are matched by visible text (robust to
class churn); structural elements use CSS.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Selectors:
    # Confirmed on pokernow.com via selector_probe (empty seats add `.table-player-seat`;
    # there is no `.you-player`, so the hero is identified by name).
    # --- seats / players ---
    seat: str = ".table-player:not(.table-player-seat)"  # occupied seats only
    seat_name: str = ".table-player-name"
    seat_stack: str = ".table-player-stack"
    seat_bet: str = ".table-player-bet-value"    # TODO: confirm during a live hand
    seat_card: str = ".table-player-cards .card"  # hero's hole cards live here
    dealer_button: str = ".dealer-button-ctn"    # TODO: confirm during a live hand

    # --- cards ---
    board_card: str = ".table-cards .card"        # TODO: confirm during a live hand

    # --- pot / amounts ---
    pot: str = ".table-pot-size"

    # --- action controls ---
    action_area: str = ".game-decisions-ctn"
    raise_input: str = ".raise-bet-value input, input.value"
    # buttons matched by lowercased visible text (substring):
    button_texts: dict = field(default_factory=lambda: {
        "fold": ["fold"],
        "check_call": ["check", "call"],
        "bet_raise": ["bet", "raise"],
        "allin": ["all in", "all-in", "allin"],
        "confirm": ["confirm", "ok", "bet", "raise"],
    })

    # --- running game log (reuse io.log_parser on this text) ---
    log_entry: str = ".log-3 .message, .game-log .message"
