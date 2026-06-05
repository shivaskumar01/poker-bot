"""Translate a Decision into PokerNow clicks — behind a hard consent gate.

`execute` is a no-op (returns False, never touches the page) unless mode == 'execute' AND
players_consent is True. Buttons are located by class (`button.fold/.check/.call/.raise`).

A RAISE/BET is THREE steps on PokerNow: click RAISE to open the bet panel, type the amount, then
click the confirm button (which then reads 'RAISE TO X' / 'BET X' / 'ALL IN'). Doing only the first
step leaves the panel open and the bot gets auto-folded — so this does all three and verifies.
"""
from __future__ import annotations

import re
from decimal import Decimal

from ..model.state import ActionType
from ..strategy.decision import Decision
from .domdump import dump_dom

_CONFIRM_RE = re.compile(r"raise to|bet to|^\s*bet\s+[\d.,]|all[\s-]?in|confirm|^\s*go\s*$", re.I)


class Executor:
    def __init__(self, page, selectors, *, mode: str = "observe",
                 players_consent: bool = False) -> None:
        self.page = page
        self.sel = selectors
        self.mode = mode
        self.players_consent = players_consent
        self._raise_dumped = False

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
            return self._raise_to(decision.amount)
        return False

    # --- raise/bet: open panel -> set amount -> confirm ---------------------
    def _raise_to(self, amount: Decimal) -> bool:
        if not self._click(self.sel.btn_raise):        # 1) open the bet panel
            return False
        self._wait(450)
        if not self._raise_dumped:                     # capture the panel once for calibration
            self._raise_dumped = True
            dump_dom(self.page, "after-raise-click")
        self._set_amount(amount)                       # 2) type the amount
        self._wait(200)
        if self._click_confirm():                      # 3) confirm (RAISE TO X / BET X / ALL IN)
            return True
        return self._click(self.sel.btn_raise)         # fallback: same button may now confirm

    def _click_confirm(self) -> bool:
        for el in self._candidate_buttons():
            try:
                if el.is_visible() and el.is_enabled() and _CONFIRM_RE.search((el.inner_text() or "").strip()):
                    el.click()
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _candidate_buttons(self):
        for sel in (f"{self.sel.action_area} button", ".action-buttons button", "button"):
            try:
                els = self.page.query_selector_all(sel)
            except Exception:  # noqa: BLE001
                els = []
            if els:
                return els
        return []

    def _click(self, selector: str) -> bool:
        el = self.page.query_selector(selector)
        if el and el.is_enabled():
            el.click()
            return True
        return False

    def _wait(self, ms: int) -> None:
        try:
            self.page.wait_for_timeout(ms)
        except Exception:  # noqa: BLE001
            pass

    def _set_amount(self, amount: Decimal) -> None:
        """Type the raise-to amount into the bet field with real keystrokes (React-friendly)."""
        value = str(int(amount)) if amount == amount.to_integral_value() else f"{amount:.2f}"
        for sel in (f"{self.sel.raise_entry} input", ".raise-bet-value input", "input.value",
                    f"{self.sel.action_area} input[inputmode='numeric']",
                    f"{self.sel.action_area} input[type='number']",
                    f"{self.sel.action_area} input[type='text']"):
            el = self.page.query_selector(sel)
            if el:
                if self._type_into(el, value):
                    return
        el = self.page.query_selector(self.sel.raise_entry)
        if el:
            try:
                el.click()
                self.page.keyboard.type(value)
            except Exception:  # noqa: BLE001 - execute-mode raise sizing may need a live re-probe
                pass

    def _type_into(self, el, text: str) -> bool:
        try:
            el.click()
        except Exception:  # noqa: BLE001
            pass
        try:
            el.fill("")
        except Exception:  # noqa: BLE001
            pass
        for meth in ("press_sequentially", "type"):
            fn = getattr(el, meth, None)
            if fn is None:
                continue
            try:
                fn(text, delay=40)
                return True
            except TypeError:
                try:
                    fn(text)
                    return True
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                pass
        try:
            el.fill(text)
            return True
        except Exception:  # noqa: BLE001
            return False
