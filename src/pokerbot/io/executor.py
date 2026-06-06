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
        self._set_dumped = False

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
            # NEVER fall back to .call here: when a check is available, PokerNow's .call button is
            # the 'BET <min>' shortcut, so clicking it would MIN-BET instead of checking.
            return self._click(self.sel.btn_check)
        if a == ActionType.CALL:
            return self._click(self.sel.btn_call)
        if a in (ActionType.BET, ActionType.RAISE):
            if self._raise_to(decision.amount):
                return True
            # Couldn't open/size the bet -> NEVER confirm a min bet. A BET is checkable, so CHECK;
            # a RAISE faces a bet (incl. an all-in jam), so CALL. Either is far better than min-betting.
            if a == ActionType.BET:
                return self._click(self.sel.btn_check)
            return self._click(self.sel.btn_call)
        return False

    # --- raise/bet: open panel -> set amount (VERIFIED) -> confirm ----------
    def _raise_to(self, amount: Decimal) -> bool:
        """Confirm ONLY a verified amount. Retries the whole open->size->confirm a few times; if it
        can never set a sane amount it returns False (the caller checks/calls) — it NEVER confirms
        the panel's default min bet. This is the fix for the recurring 'said 200, bet 5' leak."""
        for _ in range(3):
            if not self._panel_open():                 # open the bet panel (skip if a retry left it open)
                if not self._click(self.sel.btn_raise):
                    return False                       # no raise control at all (e.g. facing a jam)
                self._await_panel()                    # WAIT for the amount field to actually render
            if not self._raise_dumped:
                self._raise_dumped = True
                dump_dom(self.page, "after-raise-click")
            if self._set_amount(amount) and self._click_confirm():   # set+VERIFY, then confirm
                return True
            self._wait(160)                            # settle, then retry the open/size
        return False

    def _await_panel(self) -> None:
        """Block until the bet panel's amount field is actually on screen — a fixed delay was
        sometimes too short, leaving the field unset so the default (a min bet) got confirmed."""
        try:
            self.page.wait_for_selector(self.sel.raise_amount, state="visible", timeout=1500)
        except Exception:  # noqa: BLE001
            self._wait(300)
        self._wait(100)

    def _click_label(self, pattern: str) -> bool:
        rx = re.compile(pattern, re.I)
        for b in (self.page.query_selector_all(f"{self.sel.action_area} button, button") or []):
            try:
                if b.is_visible() and rx.search((b.inner_text() or "").strip()):
                    b.click(timeout=1500)
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _preset_near(self, target: float) -> str:
        """Clean POT-relative preset that lands a SANE (>= ~1/3 of target) amount — a real bet, never
        the min default. Tries ¾-pot, then pot, then all-in, and verifies each landed in the ballpark."""
        for label, rx in (("3/4-pot", r"3/4\s*pot"), ("pot", r"^\s*pot\s*$"), ("all-in", r"all[\s-]?in")):
            if self._click_label(rx):
                self._wait(100)
                got = self._amount_value()
                if got is not None and got >= 0.35 * target:
                    return label
        return "none"

    def activate_extra_time(self) -> bool:
        """Click PokerNow's 'ACTIVATE EXTRA TIME' to buy clock on a big decision (no-op once used
        this turn / if absent). Lets the bot tank a big pot without getting auto-folded."""
        try:
            for b in (self.page.query_selector_all(f"{self.sel.action_area} button, button") or []):
                t = (b.inner_text() or "").upper()
                if "ACTIVATE" in t and "EXTRA TIME" in t and b.is_visible() and b.is_enabled():
                    b.click(timeout=1500)
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def _panel_open(self) -> bool:
        try:
            return bool(self.page.query_selector(self.sel.raise_confirm)
                        or self.page.query_selector(self.sel.raise_amount))
        except Exception:  # noqa: BLE001
            return False

    def _click_confirm(self) -> bool:
        if self._click(self.sel.raise_confirm):        # <input type=submit value="Raise/Bet">
            return True
        for sel in (f"{self.sel.action_area} button", ".action-buttons button", "button"):  # other variants
            try:
                for b in (self.page.query_selector_all(sel) or []):
                    if b.is_visible() and _CONFIRM_RE.search((b.inner_text() or "").strip()):
                        b.click(timeout=2000)
                        return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _click(self, selector: str) -> bool:
        """Robust click: a Locator (re-resolves on re-render) with a SHORT timeout so a momentarily
        un-clickable control never hangs 30s and gets the bot auto-folded; force-clicks through a
        transient overlay on the second try."""
        try:
            loc = self.page.locator(selector).first
        except Exception:  # noqa: BLE001
            return False
        for force in (False, True):
            try:
                loc.click(timeout=2000, force=force)
                return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _wait(self, ms: int) -> None:
        try:
            self.page.wait_for_timeout(ms)
        except Exception:  # noqa: BLE001
            pass

    _NATIVE_SET = ("(n,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')"
                   ".set;s.call(n,v);n.dispatchEvent(new Event('input',{bubbles:true}));"
                   "n.dispatchEvent(new Event('change',{bubbles:true}));}")

    def _set_amount(self, amount: Decimal) -> bool:
        """Set the bet amount and VERIFY the box reads it. Returns True ONLY if a sane amount is
        confirmed (an exact set, or a clean preset in the ballpark) — so the caller will never
        confirm the panel's default min bet."""
        target = float(amount)
        cents = str(int((amount * 100).to_integral_value()))   # 100.00 -> '10000' (cents keypad)
        dec = f"{amount:.2f}"                                   # '100.00' (decimal form)
        strategies = (
            ("slider-cents", lambda: self._native(self.sel.raise_slider, cents)),
            ("type-cents", lambda: self._type_into(self.page.query_selector(self.sel.raise_amount), cents)),
            ("native-decimal", lambda: self._native(self.sel.raise_amount, dec)),
            ("native-cents", lambda: self._native(self.sel.raise_amount, cents)),
        )
        used = "none"
        for name, fn in strategies:
            try:
                fn()
            except Exception:  # noqa: BLE001
                continue
            self._wait(90)
            if self._amount_is(target):                        # exact match within ~2%
                used = name
                break
        if used == "none":                                     # exact set failed -> clean preset (never min)
            used = self._preset_near(target)
        if not self._set_dumped:                               # one-time calibration snapshot
            self._set_dumped = True
            dump_dom(self.page, f"after-set-amount target={dec} got={self._amount_str()!r} via={used}")
        return used != "none"

    def _native(self, selector: str, value: str) -> None:
        el = self.page.query_selector(selector)
        if el:
            el.evaluate(self._NATIVE_SET, value)

    def _amount_str(self) -> str:
        el = self.page.query_selector(self.sel.raise_amount)
        if not el:
            return ""
        try:
            return el.input_value() or el.get_attribute("value") or ""
        except Exception:  # noqa: BLE001
            try:
                return el.get_attribute("value") or ""
            except Exception:  # noqa: BLE001
                return ""

    def _amount_value(self) -> float | None:
        m = re.search(r"[\d.]+", self._amount_str().replace(",", ""))
        if not m:
            return None
        try:
            return float(m.group(0))
        except ValueError:
            return None

    def _amount_is(self, target: float) -> bool:
        v = self._amount_value()
        return v is not None and abs(v - target) <= max(0.25, target * 0.02)   # within a chip / 2%

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
