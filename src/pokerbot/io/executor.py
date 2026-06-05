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
        self._set_amount(amount)                       # 2) set the amount (cents-entry field)
        self._wait(250)
        return self._click_confirm()                   # 3) confirm via the SUBMIT input

    def _click_confirm(self) -> bool:
        el = self.page.query_selector(self.sel.raise_confirm)   # <input type=submit value="Raise/Bet">
        if el and el.is_enabled():
            el.click()
            return True
        for sel in (f"{self.sel.action_area} button", ".action-buttons button", "button"):  # other variants
            try:
                for b in (self.page.query_selector_all(sel) or []):
                    if b.is_visible() and b.is_enabled() and _CONFIRM_RE.search((b.inner_text() or "").strip()):
                        b.click()
                        return True
            except Exception:  # noqa: BLE001
                pass
        return False

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
        """The bet box is a CENTS-entry field (typing '1000' lands as 10.00, like the buy-in), so
        type integer cents. Also drive the cents slider as a backup so React's value updates."""
        cents = str(int((amount * 100).to_integral_value()))
        el = self.page.query_selector(self.sel.raise_amount)
        if el and self._type_into(el, cents):
            self._sync_slider(cents)
            return
        self._sync_slider(cents)

    def _sync_slider(self, cents: str) -> None:
        sl = self.page.query_selector(self.sel.raise_slider)
        if not sl:
            return
        try:                                            # set via the native setter so React's onChange fires
            sl.evaluate(
                "(n,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;"
                "s.call(n,v);n.dispatchEvent(new Event('input',{bubbles:true}));"
                "n.dispatchEvent(new Event('change',{bubbles:true}));}", cents)
        except Exception:  # noqa: BLE001
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
