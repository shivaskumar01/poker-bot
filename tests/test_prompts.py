import random

from pokerbot.io.prompts import resolve_email_login
from pokerbot.io.selectors import Selectors


class _El:
    def __init__(self, *, text="", visible=True, on_fill=None, on_click=None):
        self._t, self._v, self._f, self._c = text, visible, on_fill, on_click

    def is_visible(self):
        return self._v

    def inner_text(self):
        return self._t

    def fill(self, v):
        if self._f:
            self._f(v)

    def click(self):
        if self._c:
            self._c()

    def press(self, key):
        pass


class _FakeInbox:
    address = "bot12345@mail.tm"

    def __init__(self):
        self.waited = False

    def wait_for_code(self, **kw):
        self.waited = True
        return "428913"


class _Page:
    """Models the gate: email field -> submit -> a code field appears -> submit completes login."""

    def __init__(self, sel):
        self.sel = sel
        self.email = None
        self.code = []
        self.submitted = 0
        self.code_shown = False

    def query_selector_all(self, selector):
        if selector == self.sel.email_input:
            return [] if self.code_shown else [_El(on_fill=lambda v: setattr(self, "email", v))]
        if selector == self.sel.code_input:
            return [_El(on_fill=self.code.append)] if self.code_shown else []
        if selector.startswith("button"):
            return [_El(text="Confirm", on_click=self._submit)]
        return []

    def _submit(self):
        self.submitted += 1
        if self.email and not self.code_shown:     # after the email submit, the code field appears
            self.code_shown = True


def test_resolve_email_login_full_flow():
    page = _Page(Selectors())
    inbox = _FakeInbox()
    ok = resolve_email_login(page, page.sel, random.Random(0),
                             inbox_factory=lambda rng: inbox, sleep=lambda s: None)
    assert ok is True
    assert page.email == inbox.address             # entered a real, pollable address
    assert inbox.waited                            # polled the inbox for the code
    assert page.code == ["428913"]                 # typed the 6-digit code back in
    assert page.submitted >= 2                     # submitted email, then code


def test_resolve_email_login_noop_when_no_gate():
    class _Blank:
        sel = Selectors()

        def query_selector_all(self, selector):
            return []

    page = _Blank()
    assert resolve_email_login(page, page.sel, random.Random(0),
                               inbox_factory=lambda rng: _FakeInbox(), sleep=lambda s: None) is False


def test_resolve_email_login_inbox_failure_is_graceful():
    page = _Page(Selectors())
    notes = []

    def boom(rng):
        raise RuntimeError("mail.tm unreachable")

    ok = resolve_email_login(page, page.sel, random.Random(0), inbox_factory=boom,
                             sleep=lambda s: None, log=notes.append)
    assert ok is False
    assert any("manually" in n for n in notes)     # tells the user to finish by hand
