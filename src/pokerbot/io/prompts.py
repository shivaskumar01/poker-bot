"""PokerNow's email LOGIN gate, handled end-to-end in the Playwright thread.

The gate is two screens: (1) enter an email, (2) "confirm the code that was sent to your email".
A made-up string fails, and the two screens' inputs look alike, so this is a small STATE MACHINE
that is airtight about three things:

  * ONE inbox per login. The throwaway address is created once and reused; we never spin up a new
    inbox (which would change the address the code was sent to).
  * Screen detection by the page's TEXT, not by ambiguous input selectors. The code screen says
    "confirm the code…", so it's detected as CODE and we NEVER type the email into the code box
    (the bug this replaces).
  * Reuse across calls. The caller holds one EmailLogin instance, so polling continues against the
    same inbox even if `run()` is invoked again.

Disclosed home game: this gets the bot's own seat past a login form, not detection evasion. Any
failure (mail.tm down, code never arrives) degrades cleanly to "finish it manually".
"""
from __future__ import annotations

import random
import re
import time

from .email_inbox import TempInbox

_SUBMIT_RE = re.compile(r"authenticate|continue|submit|confirm|verify|proceed|log\s?in|sign\s?in|"
                        r"next|done|^\s*ok\s*$|^\s*go\s*$", re.I)
# The code screen is unmistakable in copy ("confirm the code", "almost there"); the email screen is
# whatever's left that still wants an address. Detecting CODE first is what prevents mis-fills.
_CODE_SCREEN = re.compile(r"confirm the code|code (that )?was sent|verification code|enter (the )?code|"
                          r"6[\s-]?digit|one[\s-]?time|almost there", re.I)
_EMAIL_SCREEN = re.compile(r"authenticate your email|enter your email|verify your email|"
                           r"e-?mail address|to proceed with your login", re.I)
_SKIP_TYPES = {"hidden", "checkbox", "radio", "button", "submit", "reset", "range", "file", "image"}


def _visible(page, selector: str):
    try:
        return [el for el in (page.query_selector_all(selector) or []) if el.is_visible()]
    except Exception:  # noqa: BLE001
        return []


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
        self._emailed = False
        self._failed = False
        self._entered: set[str] = set()
        self.done = False

    # --- public entry point -------------------------------------------------
    def run(self, page, sel, *, sleep=time.sleep, should_stop=lambda: False,
            timeout: float = 180.0) -> bool:
        """Block until the login is resolved (or times out). Returns True if it completed/advanced;
        False if there was no gate to handle or it gave up (then finish manually). Cheap no-op when
        no email/code screen is present, so it's safe to call from a polling loop."""
        if self.done or not self._gate(page, sel):
            return self.done
        deadline = time.time() + timeout
        while time.time() < deadline and not should_stop():
            if self._failed:
                return False
            screen = self._screen(page, sel)
            if screen == "email":
                self._do_email(page, sel, sleep)
                sleep(1.5)                       # let the code screen render
            elif screen == "code":
                if self._do_code(page, sel, sleep):
                    self.done = True
                    self.log("email login complete")
                    return True
                sleep(self.POLL)                 # code not in the inbox yet — keep waiting
            else:
                return self._emailed             # gate cleared on its own
        self.log("email login timed out — please finish it manually")
        return False

    # --- screen detection (TEXT first, so CODE can't be mistaken for EMAIL) --
    def _page_text(self, page) -> str:
        try:
            return (page.inner_text("body") or "").lower()
        except Exception:  # noqa: BLE001
            return ""

    def _gate(self, page, sel) -> bool:
        if self._email_fields(page, sel) or self._code_fields(page, sel):
            return True
        t = self._page_text(page)
        return bool(_CODE_SCREEN.search(t) or _EMAIL_SCREEN.search(t))

    def _screen(self, page, sel) -> str | None:
        t = self._page_text(page)
        if _CODE_SCREEN.search(t):               # unambiguous -> CODE (never fill email here)
            return "code"
        if self._email_fields(page, sel) or _EMAIL_SCREEN.search(t):
            return "email"
        if self._code_fields(page, sel):
            return "code"
        return None

    # --- field discovery ----------------------------------------------------
    def _inputs(self, page):
        out = []
        for el in (page.query_selector_all("input, textarea") or []):
            try:
                if el.is_visible() and _type_of(el) not in _SKIP_TYPES:
                    out.append(el)
            except Exception:  # noqa: BLE001
                pass
        return out

    def _email_fields(self, page, sel):
        fields = _visible(page, sel.email_input)
        if fields:
            return fields
        return [el for el in self._inputs(page) if _type_of(el) == "email"]

    def _code_fields(self, page, sel):
        fields = [el for el in _visible(page, sel.code_input) if _type_of(el) != "email"]
        if fields:
            return fields
        return [el for el in self._inputs(page) if _type_of(el) != "email"]

    # --- actions ------------------------------------------------------------
    def _do_email(self, page, sel, sleep) -> None:
        fields = self._email_fields(page, sel)
        if not fields:
            return
        if self.inbox is None:
            try:
                self.inbox = self._factory(self.rng)
            except Exception as e:  # noqa: BLE001
                self.log(f"couldn't create a verification inbox ({e}); enter an email manually")
                self._failed = True
                return
            self.address = self.inbox.address
            self.log(f"using verification email {self.address}")
        for el in fields:
            self._fill(el, self.address)
        sleep(0.4 + self.rng.random() * 0.6)
        self._submit(page)
        self._emailed = True
        self.log("submitted the email — waiting for the code")

    def _do_code(self, page, sel, sleep) -> bool:
        fields = self._code_fields(page, sel)
        if not fields:
            return False
        if self.inbox is None:
            self.log("on the code screen but no inbox is known — enter the code manually")
            self._failed = True
            return False
        code = self.inbox.poll_once(log=self.log)
        if not code or code in self._entered:
            return False
        self._entered.add(code)
        self.log(f"got code {code} — entering it")
        self._enter_code(fields, code)
        sleep(0.3 + self.rng.random() * 0.5)
        self._submit(page)
        return True

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
            last.press("Enter")                  # many OTP forms confirm on Enter
        except Exception:  # noqa: BLE001
            pass

    def _submit(self, page) -> bool:
        for el in (page.query_selector_all("button, a, [role='button'], .button, .alert-btn") or []):
            try:
                if el.is_visible() and _SUBMIT_RE.search((el.inner_text() or "").strip()):
                    el.click()
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False
