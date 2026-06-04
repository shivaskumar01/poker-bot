"""Transient PokerNow modals that can block play — handled in the Playwright thread.

The main one is PokerNow's email LOGIN gate (for its video/voice chat): it wants a real address,
emails a 6-digit code, then wants that code. `resolve_email_login` runs the whole flow — create a
genuine throwaway inbox, type the address, wait for the code field, poll the inbox for the code,
type it in — all in one blocking call. In a DISCLOSED home game this is just getting the bot's own
seat past a login form (not detection evasion). It degrades to "do it manually" on any failure, and
returns fast (two DOM checks) when no email/code field is on screen, so it's cheap to call in a loop.
"""
from __future__ import annotations

import random
import re
import time

from .email_inbox import TempInbox

_SUBMIT_RE = re.compile(r"authenticate|continue|submit|confirm|verify|proceed|log\s?in|save|done|"
                        r"join|next|^\s*ok\s*$|^\s*go\s*$", re.I)


def _visible(page, selector: str):
    try:
        return [el for el in (page.query_selector_all(selector) or []) if el.is_visible()]
    except Exception:  # noqa: BLE001
        return []


def _click_submit(page) -> bool:
    for el in (page.query_selector_all("button, a, [role='button'], .button, .alert-btn") or []):
        try:
            if el.is_visible() and _SUBMIT_RE.search((el.inner_text() or "").strip()):
                el.click()
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _fill_code(fields, code: str) -> None:
    """Single box gets the whole code; 6 single-char boxes get one digit each."""
    if len(fields) >= len(code):
        for el, ch in zip(fields, code):
            try:
                el.fill(ch)
            except Exception:  # noqa: BLE001
                pass
    else:
        try:
            fields[0].fill(code)
        except Exception:  # noqa: BLE001
            pass


def resolve_email_login(page, sel, rng: random.Random | None = None, *, inbox_factory=TempInbox.create,
                        log=lambda m: None, sleep=time.sleep, should_stop=lambda: False,
                        timeout: float = 120.0) -> bool:
    """Returns True if it advanced the email login, False if there was nothing to do (or it failed
    and the user should finish manually)."""
    rng = rng or random.Random()
    email_fields = _visible(page, sel.email_input)
    code_fields = _visible(page, sel.code_input)
    if not email_fields and not code_fields:
        return False

    inbox = None
    if email_fields:
        try:
            inbox = inbox_factory(rng)
        except Exception as e:  # noqa: BLE001
            log(f"couldn't create a verification inbox ({e}); enter an email manually")
            return False
        log(f"using verification email {inbox.address}")
        for el in email_fields:
            try:
                el.fill(inbox.address)
            except Exception:  # noqa: BLE001
                pass
        sleep(0.4 + rng.random() * 0.6)
        _click_submit(page)
        end = time.time() + 25                      # wait for the "confirm the code" field
        while time.time() < end and not should_stop():
            code_fields = _visible(page, sel.code_input)
            if code_fields:
                break
            sleep(1.5)

    if not code_fields:
        return inbox is not None                     # email step done; no code requested (yet)
    if inbox is None:
        log("a code field is showing but no inbox is known — enter the code manually")
        return False

    log("waiting for the PokerNow verification code email…")
    code = inbox.wait_for_code(timeout=timeout, sleep=sleep, should_stop=should_stop, log=log)
    if not code:
        log("no verification code arrived in time — enter it manually")
        return False
    log(f"entering verification code {code}")
    _fill_code(code_fields, code)
    sleep(0.3 + rng.random() * 0.5)
    _click_submit(page)
    return True
