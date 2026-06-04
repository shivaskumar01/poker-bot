"""Auto-seat the bot at a PokerNow table: pick a random OPEN seat, set the display name if the
game prompts for one, buy in for the configured amount, and verify we actually sat.

PokerNow's join flow (clicking an empty seat → a buy-in dialog → confirm) isn't 100% stable across
table variants, so this is deliberately defensive: selectors live in selectors.py, the confirm
button is matched by visible text, and every interaction is wrapped so a miss degrades to "sit
manually" rather than crashing. On failure `last_diag` holds what was on screen, for calibration.
"""
from __future__ import annotations

import re
import time

from .prompts import fill_email_if_prompted

_CONFIRM_RE = re.compile(r"sit|join|i'?m in|buy[\s-]?in|confirm|take a? seat|^\s*ok\s*$|^\s*go\s*$", re.I)
_SUBMIT_NAME_RE = re.compile(r"^\s*(enter|continue|ok|join|next|submit|done|play)\s*$", re.I)


class Seater:
    def __init__(self, page, sel, name: str, buy_in, rng, sleep=time.sleep) -> None:
        self.page = page
        self.sel = sel
        self.name = (name or "").strip()
        self.buy_in = buy_in
        self.rng = rng
        self._sleep = sleep
        self.last_diag = ""

    # --- tiny DOM helpers (kept small so a fake page can drive them in tests) ---
    def _visible(self, selector: str):
        out = []
        for el in self._all(selector):
            try:
                if el.is_visible():
                    out.append(el)
            except Exception:  # noqa: BLE001
                pass
        return out

    def _all(self, selector: str):
        try:
            return self.page.query_selector_all(selector) or []
        except Exception:  # noqa: BLE001
            return []

    def _click_text(self, rx: re.Pattern) -> bool:
        for el in self._all("button, a, [role='button'], .button, .alert-btn"):
            try:
                if el.is_visible() and rx.search((el.inner_text() or "").strip()):
                    el.click()
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def already_seated(self) -> bool:
        for el in self._all(self.sel.seat):
            try:
                if self.sel.hero_seat_class in (el.get_attribute("class") or ""):
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _set_name(self) -> None:
        if not self.name:
            return
        for el in self._visible(self.sel.name_input):
            try:
                el.fill(self.name)
                if not self._click_text(_SUBMIT_NAME_RE):
                    el.press("Enter")
                return
            except Exception:  # noqa: BLE001
                pass

    def _fill_buyin(self) -> None:
        for el in self._visible(self.sel.buyin_input):
            try:
                el.fill(str(self.buy_in))
                return
            except Exception:  # noqa: BLE001
                pass

    def _diag(self) -> str:
        btns = []
        for el in self._all("button, a, [role='button'], .button"):
            try:
                if el.is_visible():
                    t = (el.inner_text() or "").strip().replace("\n", " ")
                    if t:
                        btns.append(t[:24])
            except Exception:  # noqa: BLE001
                pass
        return "on-screen buttons: " + (", ".join(btns[:12]) or "(none)")

    def _pause(self, lo: float, hi: float) -> None:
        """A human-ish, randomized beat between join steps (never instant-click the seat)."""
        self._sleep(lo + self.rng.random() * (hi - lo))

    def take_seat(self, timeout: float = 25.0) -> bool:
        """Returns True once the bot occupies a seat. Idempotent: if already seated, returns at once."""
        deadline = time.time() + timeout
        # 1) clear any email-auth gate + name prompt; wait for an open seat to render
        while time.time() < deadline:
            fill_email_if_prompted(self.page, self.sel, self.rng, self._sleep)
            self._set_name()
            if self.already_seated():
                return True
            if self._visible(self.sel.empty_seat):
                break
            self._pause(0.7, 1.6)

        empties = self._visible(self.sel.empty_seat)
        if not empties:
            self.last_diag = "no open seat found. " + self._diag()
            return self.already_seated()

        # 2) take a beat to 'look at the table', then open a random open seat's buy-in dialog
        self._pause(0.8, 2.0)
        try:
            self.rng.choice(empties).click()
        except Exception:  # noqa: BLE001
            pass

        # 3) buy in + confirm; retry a few times while the dialog settles
        for _ in range(5):
            self._pause(0.6, 1.5)
            fill_email_if_prompted(self.page, self.sel, self.rng, self._sleep)
            self._set_name()          # some tables ask for the name inside the buy-in dialog
            self._fill_buyin()
            self._click_text(_CONFIRM_RE)
            if self.already_seated():
                return True
        self.last_diag = "clicked a seat but couldn't confirm the buy-in. " + self._diag()
        return self.already_seated()
