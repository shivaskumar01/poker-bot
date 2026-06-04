"""Transient PokerNow modals that can block play — handled in the Playwright thread.

PokerNow occasionally gates a table behind an email "authentication" form (for its video/voice
chat feature) that won't let you proceed while the field is blank. In a DISCLOSED home game the
bot just needs to get past the form to occupy its own seat, so we fill a randomly-generated,
syntactically-valid address and submit. This is not bot-detection evasion — the table already
knows a bot is seated; it's the same kind of setup step as filling the display-name field.
"""
from __future__ import annotations

import random
import re
import string
import time

_PROVIDERS = ("gmail.com", "outlook.com", "yahoo.com", "icloud.com", "proton.me", "hotmail.com")
_SUBMIT_RE = re.compile(r"authenticate|continue|submit|confirm|verify|save|done|join|^\s*ok\s*$", re.I)


def random_email(rng: random.Random | None = None) -> str:
    """A throwaway, valid-format address like 'qwert12@gmail.com'."""
    rng = rng or random.Random()
    name = "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(5, 9)))
    name += str(rng.randint(1, 9999))
    return f"{name}@{rng.choice(_PROVIDERS)}"


def fill_email_if_prompted(page, sel, rng: random.Random | None = None, sleep=time.sleep) -> bool:
    """If an email-auth form is visible, fill a random address + submit. Returns True if it acted."""
    rng = rng or random.Random()
    try:
        fields = [el for el in (page.query_selector_all(sel.email_input) or []) if el.is_visible()]
    except Exception:  # noqa: BLE001
        return False
    if not fields:
        return False
    email = random_email(rng)
    acted = False
    for el in fields:
        try:
            el.fill(email)
            acted = True
        except Exception:  # noqa: BLE001
            pass
    if not acted:
        return False
    sleep(0.4 + rng.random() * 0.6)               # a beat before submitting
    for el in (page.query_selector_all("button, a, [role='button'], .button, .alert-btn") or []):
        try:
            if el.is_visible() and _SUBMIT_RE.search((el.inner_text() or "").strip()):
                el.click()
                return True
        except Exception:  # noqa: BLE001
            pass
    try:
        fields[0].press("Enter")
    except Exception:  # noqa: BLE001
        pass
    return True
