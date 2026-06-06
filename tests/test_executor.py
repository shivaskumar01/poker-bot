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
