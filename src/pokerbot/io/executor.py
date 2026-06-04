"""Translate a Decision into PokerNow clicks — behind a hard consent gate.

`execute` is a no-op (returns False, never touches the page) unless mode == 'execute' AND
players_consent is True. This is the enforcement point for the project's rule: the bot only
acts in a disclosed game the operator has explicitly authorized.
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
        """Perform the action on the page. Returns False (without touching the page) if not
        authorized, or if the matching control couldn't be found."""
        if not self.can_act:
            return False
        a = decision.action
        if a == ActionType.FOLD:
            return self._click("fold")
        if a in (ActionType.CHECK, ActionType.CALL):
            return self._click("check_call")
        if a in (ActionType.BET, ActionType.RAISE):
            self._set_amount(decision.amount)
            ok = self._click("bet_raise")
            self._click("confirm")  # harmless if there is no confirm step
            return ok
        return False

    # --- DOM helpers (calibrated selectors) ---
    def _area(self):
        return self.page.query_selector(self.sel.action_area) or self.page

    def _click(self, key: str) -> bool:
        wanted = self.sel.button_texts.get(key, [])
        for b in self._area().query_selector_all("button"):
            label = (b.inner_text() or "").strip().lower()
            if label and any(t in label for t in wanted) and b.is_enabled():
                b.click()
                return True
        return False

    def _set_amount(self, amount: Decimal) -> None:
        el = self.page.query_selector(self.sel.raise_input)
        if el:
            value = str(int(amount)) if amount == amount.to_integral_value() else str(amount)
            el.fill(value)
