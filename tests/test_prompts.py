import random

from pokerbot.io.prompts import EmailLogin
from pokerbot.io.selectors import Selectors


class _El:
    def __init__(self, *, type="text", text="", visible=True, on_fill=None, on_click=None):
        self._type, self._t, self._v = type, text, visible
        self._f, self._c = on_fill, on_click

    def is_visible(self):
        return self._v

    def inner_text(self):
        return self._t

    def get_attribute(self, k):
        return self._type if k == "type" else None

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
        self.polls = 0

    def poll_once(self, senders=("pokernow",), log=lambda m: None):
        self.polls += 1
        return "428913" if self.polls >= 2 else None     # arrives on the 2nd poll


class _Page:
    """Two screens: EMAIL (an email box) then CODE ('confirm the code …' with a code box)."""

    EMAIL_TXT = "Please authenticate your email to proceed with your login"
    CODE_TXT = "We are almost there! Please confirm the code that was sent to your email"

    def __init__(self, sel, *, code_input_also_matches_email=False):
        self.sel = sel
        self.screen = "email"
        self.email = None
        self.code = []
        self.submitted = 0
        self._leak = code_input_also_matches_email     # reproduce the original mis-fill hazard

    def inner_text(self, selector):
        return self.EMAIL_TXT if self.screen == "email" else self.CODE_TXT

    def query_selector_all(self, selector):
        if selector == self.sel.email_input:
            if self.screen == "email":
                return [_El(type="email", on_fill=lambda v: setattr(self, "email", v))]
            # the hazard: on the CODE screen the code box ALSO matches the email selector
            return [_El(type="text", on_fill=self.code.append)] if self._leak else []
        if selector == self.sel.code_input:
            return [_El(type="text", on_fill=self.code.append)] if self.screen == "code" else []
        if selector in ("input, textarea",):
            return ([_El(type="email", on_fill=lambda v: setattr(self, "email", v))]
                    if self.screen == "email" else [_El(type="text", on_fill=self.code.append)])
        if selector.startswith("button"):
            return [_El(text="Confirm", on_click=self._submit)]
        return []

    def _submit(self):
        self.submitted += 1
        if self.screen == "email" and self.email:
            self.screen = "code"


def _login(inbox):
    return EmailLogin(random.Random(0), inbox_factory=lambda rng: inbox, log=lambda m: None)


def test_full_login_enters_email_then_code():
    page = _Page(Selectors())
    inbox = _FakeInbox()
    assert _login(inbox).run(page, page.sel, sleep=lambda s: None) is True
    assert page.email == inbox.address            # real address entered on screen 1
    assert page.code == ["428913"]                # the CODE (not the email) entered on screen 2
    assert page.submitted >= 2


def test_code_screen_never_gets_the_email_even_if_selectors_overlap():
    # the original bug: code box also matches the email selector. Text-based detection must still
    # treat the 'confirm the code' screen as CODE and only ever type the 6-digit code there.
    page = _Page(Selectors(), code_input_also_matches_email=True)
    inbox = _FakeInbox()
    assert _login(inbox).run(page, page.sel, sleep=lambda s: None) is True
    assert page.email == inbox.address
    assert page.code == ["428913"]                # only the code, the email was never typed here
    assert "428913" in page.code and inbox.address not in page.code


def test_one_inbox_is_reused_across_calls():
    page = _Page(Selectors())
    made = []

    def factory(rng):
        box = _FakeInbox()
        made.append(box)
        return box

    login = EmailLogin(random.Random(0), inbox_factory=factory, log=lambda m: None)
    login.run(page, page.sel, sleep=lambda s: None)
    login.run(page, page.sel, sleep=lambda s: None)   # call again
    assert len(made) == 1                              # exactly one inbox ever created


def test_noop_when_no_gate():
    class _Blank:
        sel = Selectors()

        def inner_text(self, selector):
            return "just a poker table"

        def query_selector_all(self, selector):
            return []

    page = _Blank()
    assert _login(_FakeInbox()).run(page, page.sel, sleep=lambda s: None) is False


def test_inbox_failure_is_graceful():
    page = _Page(Selectors())
    notes = []

    def boom(rng):
        raise RuntimeError("mail.tm unreachable")

    login = EmailLogin(random.Random(0), inbox_factory=boom, log=notes.append)
    assert login.run(page, page.sel, sleep=lambda s: None) is False
    assert any("manually" in n for n in notes)
