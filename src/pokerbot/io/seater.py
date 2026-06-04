"""Auto-seat the bot at a PokerNow table.

Calibrated from a live table: each empty seat shows a **SIT** button; clicking one opens a buy-in
dialog whose confirm button is **REQUEST THE SEAT** (this table gates seats behind a request the
host approves). So: click a random SIT button → fill the buy-in → click REQUEST THE SEAT → wait to
be seated (`.you-player` appears). Everything is frame-aware and wrapped so a miss degrades to "sit
manually" with a printed DOM snapshot for calibration, never a crash.
"""
from __future__ import annotations

import re
import time

from .domdump import dump_dom, scopes
from .prompts import EmailLogin

# A seat's own 'SIT' / 'SIT HERE' button (NOT 'request the seat', NOT 'sit down').
_SIT_RE = re.compile(r"^\s*sit(\s+here)?\s*$", re.I)
# Confirm button for the buy-in dialog, in priority order (this table uses 'REQUEST THE SEAT').
_CONFIRM_SEQ = (
    r"request the seat|request seat",
    r"buy[\s-]?in",
    r"i'?m in|\bim in\b",
    r"sit down|take a? seat|join the (game|table)|join now",
    r"\bjoin\b|confirm|proceed|^\s*ok\s*$|^\s*go\s*$",
)
_SUBMIT_NAME_RE = re.compile(r"^\s*(enter|continue|ok|join|next|submit|done|play)\s*$", re.I)
_BTN_SEL = "button, a, [role='button'], .button, .alert-btn"


class Seater:
    def __init__(self, page, sel, name: str, buy_in, rng, sleep=time.sleep,
                 log=lambda m: None, should_stop=lambda: False) -> None:
        self.page = page
        self.sel = sel
        self.name = (name or "").strip()
        self.buy_in = buy_in
        self.rng = rng
        self._sleep = sleep
        self.log = log
        self.should_stop = should_stop
        self.login = EmailLogin(rng, log=log)        # one inbox for the whole login
        self.last_diag = ""

    def _email(self) -> None:
        self.login.run(self.page, self.sel, sleep=self._sleep, should_stop=self.should_stop)

    # --- frame-aware DOM helpers --------------------------------------------
    def _visible(self, selector: str):
        out = []
        for fr in scopes(self.page):
            try:
                out += [el for el in (fr.query_selector_all(selector) or []) if el.is_visible()]
            except Exception:  # noqa: BLE001
                pass
        return out

    def _buttons(self):
        return self._visible(_BTN_SEL)

    def _click_first(self, rx: re.Pattern, els=None) -> bool:
        for el in (els if els is not None else self._buttons()):
            try:
                if rx.search((el.inner_text() or "").strip()):
                    el.click()
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _confirm_seat(self) -> bool:
        btns = self._buttons()
        for pat in _CONFIRM_SEQ:                      # honor priority order
            if self._click_first(re.compile(pat, re.I), btns):
                return True
        return False

    def _sit_buttons(self):
        return [el for el in self._buttons() if _SIT_RE.search((el.inner_text() or "").strip())]

    def _open_seat_available(self) -> bool:
        return bool(self._sit_buttons() or self._visible(self.sel.empty_seat))

    def _open_seat(self) -> bool:
        target = self._sit_buttons() or self._visible(self.sel.empty_seat)
        if not target:
            return False
        try:
            self.rng.choice(target).click()
            return True
        except Exception:  # noqa: BLE001
            return False

    def already_seated(self) -> bool:
        for fr in scopes(self.page):
            try:
                for el in (fr.query_selector_all(self.sel.seat) or []):
                    if self.sel.hero_seat_class in (el.get_attribute("class") or ""):
                        return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _set_name(self, submit: bool = False) -> None:
        """Fill the display-name field. `submit` only for the standalone join prompt — NEVER in the
        buy-in dialog, where pressing Enter / clicking a button closes it before we can buy in."""
        if not self.name:
            return
        for el in self._visible(self.sel.name_input):
            try:
                el.fill(self.name)
                if submit and not self._click_first(_SUBMIT_NAME_RE):
                    el.press("Enter")
                return
            except Exception:  # noqa: BLE001
                pass

    def _buyin_dialog_open(self) -> bool:
        if self._visible(self.sel.buyin_input):
            return True
        rx = re.compile(r"request the seat|buy[\s-]?in|i'?m in", re.I)
        return any(rx.search((el.inner_text() or "").strip()) for el in self._buttons())

    def _buyin_text(self) -> str:
        """A whole-number buy-in types as '200' (not '200.00'); keep cents only when non-zero."""
        amt = self.buy_in
        try:
            return str(int(amt)) if amt == amt.to_integral_value() else f"{amt:.2f}"
        except Exception:  # noqa: BLE001
            return str(amt)

    def _fill_buyin(self) -> bool:
        text = self._buyin_text()
        for el in self._visible(self.sel.buyin_input):
            if self._type_value(el, text):
                return True
        return False

    def _type_value(self, el, text: str) -> bool:
        """Type into a (React-controlled) field with real keystrokes so onChange fires; fall back
        to fill(). Clears any prefill first."""
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

    def _diag(self) -> str:
        btns = []
        for el in self._buttons():
            try:
                t = (el.inner_text() or "").strip().replace("\n", " ")
                if t:
                    btns.append(t[:24])
            except Exception:  # noqa: BLE001
                pass
        return "on-screen buttons: " + (", ".join(btns[:16]) or "(none)")

    def _pause(self, lo: float, hi: float) -> None:
        self._sleep(lo + self.rng.random() * (hi - lo))

    # --- the flow -----------------------------------------------------------
    def take_seat(self, timeout: float = 60.0) -> bool:
        """Returns True once the bot occupies a seat. Idempotent: returns at once if already seated."""
        self._email()                                 # finish any email-login gate first
        if self.already_seated():
            return True
        dump_dom(self.page, "on-open")                # initial screen (name prompt? seats?)

        # phase 1 — handle the standalone join name prompt + wait for a SIT button / open seat
        seat_deadline = time.time() + min(20.0, timeout)
        while time.time() < seat_deadline and not self.should_stop():
            self._email()
            self._set_name(submit=True)               # the join name prompt is meant to be submitted
            if self.already_seated():
                return True
            if self._open_seat_available():
                break
            self._pause(0.7, 1.6)
        if not self._open_seat_available():
            dump_dom(self.page, "no-open-seat")
            self.last_diag = "no SIT button / open seat found. " + self._diag()
            return self.already_seated()

        # phase 2 — take a seat, then buy in. CRITICAL: never submit the name here (closes the dialog)
        self._pause(0.6, 1.4)
        self._open_seat()                             # click a random SIT button
        self._pause(1.2, 2.0)
        dump_dom(self.page, "after-clicking-SIT")     # the real buy-in dialog
        self._set_name(submit=False)                  # fill name if the dialog has one — do NOT submit
        self._fill_buyin()
        self._pause(0.4, 0.9)
        self._confirm_seat()
        self._pause(0.8, 1.4)
        dump_dom(self.page, "after-confirm")

        # phase 3 — wait to be seated (the table may require host approval of the request)
        end = time.time() + timeout
        while time.time() < end and not self.should_stop():
            if self.already_seated():
                return True
            self.log("requested the seat — waiting to be seated (approve it in PokerNow if asked)…")
            self._email()
            if self._buyin_dialog_open():             # only re-try while the dialog is actually open
                self._fill_buyin()
                self._confirm_seat()
            self._pause(1.5, 2.5)

        dump_dom(self.page, "seat-timeout")
        self.last_diag = "clicked SIT but couldn't complete the buy-in/seat. " + self._diag()
        return self.already_seated()
