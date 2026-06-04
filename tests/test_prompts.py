import random
import re

from pokerbot.io.prompts import fill_email_if_prompted, random_email
from pokerbot.io.selectors import Selectors


def test_random_email_format():
    for seed in range(20):
        e = random_email(random.Random(seed))
        assert re.fullmatch(r"[a-z]+\d+@[a-z]+\.[a-z]+", e), e


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


class _Page:
    def __init__(self, sel, has_email=True):
        self.sel, self.has_email = sel, has_email
        self.filled = None
        self.clicked = False

    def query_selector_all(self, selector):
        if selector == self.sel.email_input:
            return [_El(on_fill=lambda v: setattr(self, "filled", v))] if self.has_email else []
        if selector.startswith("button"):
            return [_El(text="Authenticate", on_click=lambda: setattr(self, "clicked", True))]
        return []


def test_fills_and_submits_when_email_prompted():
    page = _Page(Selectors())
    ok = fill_email_if_prompted(page, page.sel, random.Random(0), sleep=lambda s: None)
    assert ok is True
    assert page.filled and "@" in page.filled
    assert page.clicked is True


def test_noop_when_no_email_field():
    page = _Page(Selectors(), has_email=False)
    ok = fill_email_if_prompted(page, page.sel, random.Random(0), sleep=lambda s: None)
    assert ok is False
    assert page.filled is None
