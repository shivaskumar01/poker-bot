import random
from decimal import Decimal as D

from pokerbot.io.seater import Seater
from pokerbot.io.selectors import Selectors


class _El:
    def __init__(self, *, cls="", text="", on_click=None, on_fill=None):
        self._cls, self._text, self._on_click, self._on_fill = cls, text, on_click, on_fill

    def is_visible(self):
        return True

    def inner_text(self):
        return self._text

    def get_attribute(self, k):
        return self._cls if k == "class" else None

    def click(self):
        if self._on_click:
            self._on_click()

    def fill(self, v):
        if self._on_fill:
            self._on_fill(v)

    def press(self, key):
        pass


class _Page:
    """Models PokerNow's join flow: empty seats -> click one -> buy-in dialog -> confirm -> seated."""

    def __init__(self, sel, seated=False, no_seats=False):
        self.sel = sel
        self.seated = seated
        self.no_seats = no_seats
        self.seat_clicked = False
        self.buyin = None
        self.name = None

    def _click_seat(self):
        self.seat_clicked = True

    def _confirm(self):
        if self.buyin is not None:        # only sits down once a buy-in was entered
            self.seated = True

    def query_selector_all(self, selector):
        s = self.sel
        if selector == s.seat:
            return [_El(cls="table-player you-player")] if self.seated else []
        if selector == s.empty_seat:
            if self.seated or self.no_seats:
                return []
            return [_El(on_click=self._click_seat), _El(on_click=self._click_seat)]
        if selector == s.name_input:
            if self.seated or self.seat_clicked:
                return []
            return [_El(on_fill=lambda v: setattr(self, "name", v))]
        if selector == s.buyin_input:
            if self.seat_clicked and not self.seated:
                return [_El(on_fill=lambda v: setattr(self, "buyin", v))]
            return []
        if selector.startswith("button"):
            if self.seated:
                return []
            return [_El(text="Sit Down", on_click=self._confirm)] if self.seat_clicked \
                else [_El(text="Continue")]
        return []


def _seater(page, name="robot", buy_in=D("100.00")):
    return Seater(page, page.sel, name, buy_in, random.Random(0), sleep=lambda s: None)


def test_take_seat_picks_open_seat_and_buys_in():
    page = _Page(Selectors())
    s = _seater(page)
    assert s.take_seat(timeout=5) is True
    assert page.seated and page.seat_clicked
    assert page.name == "robot" and page.buyin == "100.00"     # decimals preserved


def test_already_seated_is_idempotent():
    page = _Page(Selectors(), seated=True)
    s = _seater(page)
    assert s.take_seat(timeout=5) is True
    assert page.seat_clicked is False                           # didn't try to take another seat


def test_no_open_seat_reports_diagnostics():
    page = _Page(Selectors(), no_seats=True)
    s = _seater(page)
    assert s.take_seat(timeout=0.1) is False
    assert "no open seat" in s.last_diag
