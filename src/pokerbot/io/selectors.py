"""PokerNow.com DOM selectors — calibrated from a live hand via selector_probe.

Cards are `.card-container` elements whose classes encode them: `card-<suit>` (s/h/d/c) and
`card-s-<rank>`, with `.flipped` meaning face-up. The hero's seat carries `.you-player`
(and `.decision-current` on its turn). Action buttons are identified by class, not text.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Selectors:
    # --- seats / players (empty seats add .table-player-seat; hero seat adds .you-player) ---
    seat: str = ".table-player:not(.table-player-seat)"
    seat_name: str = ".table-player-name"
    seat_stack: str = ".table-player-stack"
    hero_seat_class: str = "you-player"          # substring test on a seat's class
    current_actor_class: str = "decision-current"
    folded_class: str = "fold"                    # appears in a folded seat's class

    # --- joining the table (auto-seat): empty seats are .table-player.table-player-seat; clicking
    #     one opens a name prompt (first time) then a buy-in dialog. Best-effort + text fallbacks. ---
    empty_seat: str = ".table-player.table-player-seat"
    name_input: str = (".you-name-ctn input, [class*='name'] input[type='text'], "
                       "input[name*='name' i], input[placeholder*='name' i]")
    # PokerNow sometimes gates the table behind an email 'authentication' form (video/voice chat),
    # then asks for a 6-digit code it emails you (code_input may be one box or 6 single-char boxes).
    email_input: str = ("input[type='email'], [class*='email'] input, "
                        "input[name*='email' i], input[placeholder*='email' i]")
    code_input: str = ("input[autocomplete='one-time-code'], input[name*='code' i], "
                       "input[placeholder*='code' i], [class*='verif'] input, [class*='code'] input, "
                       "input[maxlength='6'], input[maxlength='1']")
    # PokerNow's seat dialog: the stack box is <input type=text placeholder="Intended Stack"
    # inputmode=numeric> with NO class/name/id — so match it by placeholder/inputmode first.
    buyin_input: str = ("input[placeholder*='intended' i], input[placeholder*='stack' i], "
                        "input[placeholder*='buy' i], input[inputmode='numeric'], "
                        "[class*='buyin'] input, [class*='buy-in'] input, [class*='stack'] input, "
                        "input[type='number'], input[type='range']")

    # --- cards (.card-container with card-<suit> + card-s-<rank>; .flipped = face up) ---
    hero_card: str = ".you-player .card-container.flipped"
    board_card: str = ".table-cards .card-container.flipped"

    # --- dealer button (container class carries dealer-position-<seat#>) ---
    dealer_button: str = ".dealer-button-ctn"

    # --- pot ---
    pot: str = ".table-pot-size"

    # --- blinds level display (best-effort; read_blinds also scans the page text) ---
    blinds: str = ".table-game-infos, [class*='blind-value'], [class*='game-name']"

    # --- action controls (by class; text is unreliable) ---
    action_area: str = ".game-decisions-ctn"
    btn_fold: str = ".game-decisions-ctn button.fold"
    btn_check: str = ".game-decisions-ctn button.check"
    btn_call: str = ".game-decisions-ctn button.call"
    btn_raise: str = ".game-decisions-ctn button.raise"
    raise_entry: str = ".entry-raise .entry-ctn"   # custom widget; execute-mode TODO

    # --- running log (opened via the LOG/LEDGER button) — entry selector still TBD ---
    show_log_button: str = ".show-log-button"
    log_entry: str = ".log-3 .message"
