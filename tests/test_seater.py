import random
from decimal import Decimal as D

from pokerbot.io.seater import Seater
from pokerbot.io.selectors import Selectors


class _El:
    def __init__(self, *, text="", attrs=None, on_click=None, on_fill=None):
        self._text = text
        self._attrs = attrs or {}
        self._on_click = on_click
        self._on_fill = on_fill

    def is_visible(self):
        return True

    def inner_text(self):
        return self._text

    def get_attribute(self, k):
        return self._attrs.get(k)

    def click(self):
        if self._on_click:
            self._on_click()

    def fill(self, v):
        if self._on_fill:
            self._on_fill(v)

    def press(self, key):
        pass


class _Page:
    """PokerNow seating as observed live: empty seats each show a SIT button; clicking one opens a
    buy-in dialog whose confirm button is 'REQUEST THE SEAT'."""

    def __init__(self, sel, seated=False, no_seats=False):
        self.sel = sel
        self.seated = seated
        self.no_seats = no_seats
        self.sit_clicked = False
        self.buyin = None
        self.requested = False

    def inner_text(self, selector):
        return "poker table"

    def _sit(self):
        self.sit_clicked = True

    def _request(self):
        self.requested = True
        if self.buyin is not None:        # seat granted once a buy-in was entered
            self.seated = True

    def query_selector_all(self, selector):
        s = self.sel
        if selector == s.seat:
            return [_El(attrs={"class": "table-player you-player"})] if self.seated else []
        if selector == s.empty_seat:
            return []                     # this table exposes SIT buttons, not clickable seat divs
        if selector == s.buyin_input:
            if self.sit_clicked and not self.seated:
                return [_El(on_fill=lambda v: setattr(self, "buyin", v))]
            return []
        if selector in (s.name_input, s.email_input, s.code_input):
            return []
        if selector.startswith("button") or "button" in selector:
            if self.seated:
                return []
            if not self.sit_clicked:
                return [_El(text="SIT", on_click=self._sit) for _ in range(4)]
            return [_El(text="REQUEST THE SEAT", on_click=self._request)]
        if "input" in selector:           # generic scan (dump)
            return ([_El(on_fill=lambda v: setattr(self, "buyin", v))]
                    if self.sit_clicked and not self.seated else [])
        return []


def _seater(page, name="robot", buy_in=D("200.00")):
    return Seater(page, page.sel, name, buy_in, random.Random(0), sleep=lambda s: None)


def test_take_seat_clicks_sit_then_requests_with_buyin():
    page = _Page(Selectors())
    s = _seater(page)
    assert s.take_seat(timeout=5) is True
    assert page.sit_clicked and page.requested
    assert page.buyin == "20000"           # cents field: 200.00 must be typed as '20000'
    assert page.seated


def test_buyin_is_typed_as_cents():
    page = _Page(Selectors())
    for amount, typed in [("200.00", "20000"), ("200", "20000"), ("200.50", "20050"),
                          ("1.00", "100"), ("55.25", "5525")]:
        assert _seater(page, buy_in=D(amount))._buyin_text() == typed


def test_already_seated_is_idempotent():
    page = _Page(Selectors(), seated=True)
    s = _seater(page)
    assert s.take_seat(timeout=5) is True
    assert page.sit_clicked is False       # never tried to take another seat


def test_no_open_seat_reports_diagnostics():
    page = _Page(Selectors(), no_seats=True)
    page.query_selector_all = lambda selector: []   # nothing on the table at all
    s = _seater(page)
    assert s.take_seat(timeout=0.1) is False
    assert "no SIT button" in s.last_diag
