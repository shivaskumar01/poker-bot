"""PokerNow's email LOGIN gate, handled end-to-end in the Playwright thread.

The gate is two screens: (1) enter an email, (2) "confirm the code that was sent to your email".
Earlier versions decided which screen they were on by reading inputs/text, which broke when the
code box looked like an email box (and when the modal lives in an iframe), the bot typed the email
into the code box. This version is a STATE MACHINE that does not depend on guessing the screen:

  * ONE inbox per login (created once, reused; the caller holds the instance).
  * PHASE-based: before we've submitted an email we're in EMAIL phase; after, we're in CODE phase
    and we ONLY ever type the 6-digit code, never the email, so a mis-fill is impossible.
  * Searches EVERY frame (iframe-safe) for the field and submit button.
  * If it has the code but can't find the box, it surfaces the code to the UI so the user types it.
  * Prints a full DOM snapshot of the gate (all frames, inputs, buttons) for calibration.

Disclosed home game: this gets the bot's own seat past a login form, not detection evasion.
"""
from __future__ import annotations

import random
import re
import time

from .domdump import dump_dom, scopes
from .email_inbox import TempInbox

_SUBMIT_RE = re.compile(r"authenticate|continue|submit|confirm|verify|proceed|log\s?in|sign\s?in|"
                        r"next|done|^\s*ok\s*$|^\s*go\s*$", re.I)
_CODE_SCREEN = re.compile(r"confirm the code|code (that )?was sent|verification code|enter (the )?code|"
                          r"6[\s-]?digit|one[\s-]?time|almost there", re.I)
_EMAIL_SCREEN = re.compile(r"authenticate your email|enter your email|verify your email|"
                           r"e-?mail address|to proceed with your login", re.I)
_SKIP_TYPES = {"hidden", "checkbox", "radio", "button", "submit", "reset", "range", "file", "image"}


def _type_of(el) -> str:
    try:
        return (el.get_attribute("type") or "text").lower()
    except Exception:  # noqa: BLE001
        return "text"


class EmailLogin:
    """Drives the PokerNow email-login gate to completion. Hold ONE per session."""

    POLL = 3.0

    def __init__(self, rng: random.Random | None = None, *, inbox_factory=TempInbox.create,
                 log=lambda m: None) -> None:
        self.rng = rng or random.Random()
        self._factory = inbox_factory
        self.log = log
        self.inbox = None
        self.address = None
        self.code = None
        self._emailed = False
        self._failed = False
        self._dumped = False
        self._entered: set[str] = set()
        self.done = False

    # --- public entry point -------------------------------------------------
    def run(self, page, sel, *, sleep=time.sleep, should_stop=lambda: False,
            timeout: float = 180.0) -> bool:
        if self.done:
            return True
        if not self._emailed and not self._gate(page, sel):
            return False
        self._dump(page, "gate detected")
        deadline = time.time() + timeout
        while time.time() < deadline and not should_stop():
            if self._failed:
                return False
            if not self._emailed:
                if not self._enter_email(page, sel, sleep):
                    if not self._gate(page, sel):
                        return False                 # gate vanished before we acted
                    sleep(1.0)
                else:
                    sleep(2.0)                       # let the code screen render
                continue
            # CODE phase, email already sent, so we ONLY enter codes from here on
            if self._enter_code_when_ready(page, sel, sleep):
                self.done = True
                self.log("email login complete")
                return True
            if self.code is None and not self._gate(page, sel):
                self.done = True                     # gate cleared, no code ever needed
                return True
            sleep(self.POLL)
        if self.code:
            self.log(f"timed out filling it, type this code into PokerNow yourself: {self.code}")
        else:
            self.log("no verification code arrived, PokerNow may block disposable email; "
                     "finish the login manually")
        return self.done

    # --- phases -------------------------------------------------------------
    def _enter_email(self, page, sel, sleep) -> bool:
        fields = self._email_fields(page, sel)
        if not fields:
            return False
        if self.inbox is None:
            try:
                self.inbox = self._factory(self.rng)
            except Exception as e:  # noqa: BLE001
                self.log(f"couldn't create a verification inbox ({e}); enter an email manually")
                self._failed = True
                return False
            self.address = self.inbox.address
            self.log(f"using verification email {self.address}")
        for el in fields:
            self._fill(el, self.address)
        sleep(0.4 + self.rng.random() * 0.6)
        self._submit(page)
        self._emailed = True
        self.log("submitted the email, waiting for the code email to arrive")
        return True

    def _enter_code_when_ready(self, page, sel, sleep) -> bool:
        if self.inbox is None:
            self._failed = True
            return False
        if self.code is None:
            self.code = self.inbox.poll_once(log=self.log)
            if self.code:
                self.log(f"got verification code {self.code} from the email")
        if not self.code:
            return False
        fields = self._code_fields(page, sel)
        if not fields:
            self._dump(page, "have code, no code box")
            self.log(f"couldn't find the code box, type this code into PokerNow yourself: {self.code}")
            return False
        if self.code in self._entered:
            return False
        self._entered.add(self.code)
        self.log(f"entering verification code {self.code}")
        self._enter_code(fields, self.code)
        sleep(0.3 + self.rng.random() * 0.5)
        self._submit(page)
        return True

    # --- frame-aware DOM access (handles the modal living in an iframe) ------
    def _all_visible(self, page, selector):
        out = []
        for fr in scopes(page):
            try:
                out += [el for el in (fr.query_selector_all(selector) or []) if el.is_visible()]
            except Exception:  # noqa: BLE001
                pass
        return out

    def _text(self, page) -> str:
        parts = []
        for fr in scopes(page):
            try:
                parts.append(fr.inner_text("body") or "")
            except Exception:  # noqa: BLE001
                pass
        return " ".join(parts).lower()

    def _gate(self, page, sel) -> bool:
        # input-presence only, cheap enough to call every loop tick (no full-page inner_text scan,
        # which was ~100ms of hot-loop waste each time). The login screens always carry their input.
        return bool(self._all_visible(page, sel.email_input) or self._all_visible(page, sel.code_input))

    def _inputs(self, page):
        return [el for el in self._all_visible(page, "input, textarea") if _type_of(el) not in _SKIP_TYPES]

    def _email_fields(self, page, sel):
        fields = self._all_visible(page, sel.email_input)
        return fields or [el for el in self._inputs(page) if _type_of(el) == "email"]

    def _code_fields(self, page, sel):
        fields = [el for el in self._all_visible(page, sel.code_input) if _type_of(el) != "email"]
        return fields or [el for el in self._inputs(page) if _type_of(el) != "email"]

    # --- low-level DOM ------------------------------------------------------
    def _fill(self, el, text) -> None:
        try:
            el.fill(text)
        except Exception:  # noqa: BLE001
            pass

    def _enter_code(self, fields, code: str) -> None:
        """One box gets the whole code; six single-char boxes get one digit each."""
        if len(fields) >= len(code):
            for el, ch in zip(fields, code):
                self._fill(el, ch)
            last = fields[len(code) - 1]
        else:
            self._fill(fields[0], code)
            last = fields[0]
        try:
            last.press("Enter")                      # many OTP forms confirm on Enter
        except Exception:  # noqa: BLE001
            pass

    def _submit(self, page) -> bool:
        for fr in scopes(page):
            try:
                for el in (fr.query_selector_all("button, a, [role='button'], .button, .alert-btn") or []):
                    if el.is_visible() and _SUBMIT_RE.search((el.inner_text() or "").strip()):
                        el.click()
                        return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _dump(self, page, tag: str) -> None:
        dump_dom(page, f"email-gate {tag}")
