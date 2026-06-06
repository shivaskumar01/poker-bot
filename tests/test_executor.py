from decimal import Decimal as D

from pokerbot.io.executor import Executor
from pokerbot.io.selectors import Selectors
from pokerbot.model.state import ActionType
from pokerbot.strategy.decision import Decision


class _Loc:
    """Stands in for page.locator(sel).first — clicks resolve to a button name or 'miss'."""

    def __init__(self, sel, page):
        self._sel, self._page = sel, page

    @property
    def first(self):
        return self

    def click(self, timeout=None, force=False):
        if "button.check" in self._sel and self._page.has_check:
            self._page.clicked.append("check")
            return
        if "button.call" in self._sel and self._page.has_call:
            self._page.clicked.append("call")        # PokerNow's 'BET <min>' shortcut when checkable
            return
        raise RuntimeError("not actionable")


class _Page:
    def __init__(self, has_check=True, has_call=True):
        self.clicked = []
        self.has_check = has_check
        self.has_call = has_call

    def locator(self, sel):
        return _Loc(sel, self)

    def query_selector(self, sel):
        return None


def _ex(page):
    return Executor(page, Selectors(), mode="execute", players_consent=True)


def test_check_clicks_check_only():
    page = _Page(has_check=True, has_call=True)
    assert _ex(page).execute(Decision(ActionType.CHECK, D("0"), "give up and check")) is True
    assert page.clicked == ["check"]                  # checked — never touched the 'BET min' button


def test_check_never_min_bets_when_check_click_fails():
    page = _Page(has_check=False, has_call=True)       # check momentarily not clickable
    assert _ex(page).execute(Decision(ActionType.CHECK, D("0"), "check")) is False
    assert "call" not in page.clicked                  # crucially did NOT fall back to the min-bet


def test_call_clicks_call():
    page = _Page(has_check=True, has_call=True)
    assert _ex(page).execute(Decision(ActionType.CALL, D("2"), "call")) is True
    assert page.clicked == ["call"]


# --- bet panel: never confirm an unverified (min) amount ---------------------
class _BetEl:
    def __init__(self, kind, page):
        self.kind, self.page = kind, page

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def inner_text(self):
        return self.kind

    def input_value(self):
        return self.page.amount_str()

    def get_attribute(self, k):
        return self.page.amount_str() if k == "value" else None

    def evaluate(self, js, v):
        self.page.try_set(v)              # the native value-setter on slider/input

    def fill(self, v):
        if v:
            self.page.try_set(v)

    def click(self, timeout=None, force=False):
        self.page.click_kind(self.kind)

    def press(self, k):
        pass


class _BetLoc:
    def __init__(self, sel, page):
        self.sel, self.page = sel, page

    @property
    def first(self):
        return self

    def click(self, timeout=None, force=False):
        for key, kind in (("button.raise", "raise"), ("button.check", "check"),
                          ("button.call", "call"), ("submit", "confirm")):
            if key in self.sel:
                if kind == "confirm" and not self.page.panel_open:
                    raise RuntimeError("no panel")
                self.page.click_kind(kind)
                return
        raise RuntimeError("miss")


class _BetPage:
    """Models PokerNow's bet panel: opens with a MIN default; settable via slider/native; presets
    set a pot fraction; confirm commits whatever is in the box."""

    def __init__(self, *, settable=True, presets=True, pot=200.0, minbet=2.0):
        self.settable, self.presets, self.pot, self.minbet = settable, presets, pot, minbet
        self.panel_open = False
        self.amount = None
        self.confirmed = None
        self.actions = []

    def amount_str(self):
        return f"{self.amount:.2f}" if self.amount is not None else ""

    def try_set(self, v):
        if self.settable and self.panel_open:
            try:
                self.amount = int(v) / 100.0          # cents-entry
            except ValueError:
                try:
                    self.amount = float(v)
                except ValueError:
                    pass

    def click_kind(self, kind):
        if kind == "raise":
            self.panel_open, self.amount = True, self.minbet     # opens with the min default
        elif kind == "confirm" and self.panel_open and self.amount is not None:
            self.confirmed, self.panel_open = self.amount, False
        elif kind in ("check", "call", "fold"):
            self.actions.append(kind)
        elif kind.upper().endswith("POT") or kind.upper() == "ALL IN":
            frac = {"1/2 POT": 0.5, "3/4 POT": 0.75, "POT": 1.0, "ALL IN": 99}.get(kind.upper())
            if frac and self.panel_open:
                self.amount = self.pot * frac if frac < 90 else self.pot * 5

    def locator(self, sel):
        return _BetLoc(sel, self)

    def query_selector(self, sel):
        if "submit" in sel:
            return _BetEl("confirm", self) if self.panel_open else None
        if "value" in sel or "inputmode" in sel or "slider" in sel or "range" in sel:
            return _BetEl("amount", self) if self.panel_open else None
        if "button.raise" in sel:
            return _BetEl("raise", self)
        if "button.check" in sel:
            return _BetEl("check", self)
        if "button.call" in sel:
            return _BetEl("call", self)
        return None

    def query_selector_all(self, sel):
        if "button" in sel and self.panel_open and self.presets:
            return [_BetEl(t, self) for t in ("1/2 POT", "3/4 POT", "POT", "ALL IN")]
        return []

    def wait_for_selector(self, sel, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass


def test_bet_sets_and_confirms_the_right_amount():
    page = _BetPage(settable=True, pot=200.0)
    assert _ex(page).execute(Decision(ActionType.BET, D("150.00"), "value bet")) is True
    assert page.confirmed is not None and abs(page.confirmed - 150.0) <= 3   # not the min default


def test_bet_falls_back_to_preset_not_min_when_typing_fails():
    page = _BetPage(settable=False, presets=True, pot=200.0)   # slider/native won't set, presets work
    assert _ex(page).execute(Decision(ActionType.BET, D("150.00"), "value bet")) is True
    assert page.confirmed is not None and page.confirmed >= 0.35 * 150   # a sane bet, never the 2.0 min


def test_bet_checks_rather_than_min_betting_when_amount_cannot_be_set():
    page = _BetPage(settable=False, presets=False, pot=200.0)  # nothing can size the bet
    assert _ex(page).execute(Decision(ActionType.BET, D("150.00"), "value bet")) is True
    assert page.confirmed is None        # NEVER confirmed a min bet
    assert page.actions == ["check"]     # fell back to a free check instead


def test_raise_calls_rather_than_min_raising_when_amount_cannot_be_set():
    page = _BetPage(settable=False, presets=False, pot=200.0)
    assert _ex(page).execute(Decision(ActionType.RAISE, D("150.00"), "value raise")) is True
    assert page.confirmed is None
    assert page.actions == ["call"]      # facing a bet -> call instead of a min-raise
