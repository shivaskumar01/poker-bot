"""Translate a Decision into PokerNow clicks — behind a hard consent gate.

`execute` is a no-op (returns False, never touches the page) unless mode == 'execute' AND
players_consent is True. Buttons are located by class (`button.fold/.check/.call/.raise`).
"""
from __future__ import annotations

from decimal import Decimal

from ..model.state import ActionType
from ..strategy.decision import Decision


class Executor:
    def __init__(self, page, selectors, *, mode: str = "observe",
                 players_consent: bool = False) -> None:
        self.page = page
        self.sel = selectors
        self.mode = mode
        self.players_consent = players_consent

    @property
    def can_act(self) -> bool:
        return self.mode == "execute" and self.players_consent

    def execute(self, decision: Decision) -> bool:
        """Perform the action. Returns False (touching nothing) if unauthorized or the control
        isn't found."""
        if not self.can_act:
            return False
        a = decision.action
        if a == ActionType.FOLD:
            return self._click(self.sel.btn_fold)
        if a == ActionType.CHECK:
            return self._click(self.sel.btn_check) or self._click(self.sel.btn_call)
        if a == ActionType.CALL:
            return self._click(self.sel.btn_call) or self._click(self.sel.btn_check)
        if a in (ActionType.BET, ActionType.RAISE):
            self._set_amount(decision.amount)
            return self._click(self.sel.btn_raise)
        return False

    def _click(self, selector: str) -> bool:
        el = self.page.query_selector(selector)
        if el and el.is_enabled():
            el.click()
            return True
        return False

    def _set_amount(self, amount: Decimal) -> None:
        # PokerNow's raise entry is a custom widget (.entry-raise .entry-ctn) rather than a
        # plain <input>; exact-amount entry is calibrated in execute-mode bring-up.
        el = self.page.query_selector(self.sel.raise_entry)
        if el is None:
            return
        value = str(int(amount)) if amount == amount.to_integral_value() else str(amount)
        inp = el.query_selector("input")
        try:
            if inp:
                inp.fill(value)
            else:
                el.click()
                self.page.keyboard.type(value)
        except Exception:
            pass
