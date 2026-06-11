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


class _Marker:
    """An action-area button carrying an AMOUNT (e.g. 'CALL 2.00') — the real-turn marker."""

    def __init__(self, text="CALL 2.00"):
        self._t = text

    def is_visible(self):
        return True

    def inner_text(self):
        return self._t

    def click(self, timeout=None, force=False):
        pass


class _Page:
    def __init__(self, has_check=True, has_call=True, my_turn=True):
        self.clicked = []
        self.has_check = has_check
        self.has_call = has_call
        self.my_turn = my_turn

    def locator(self, sel):
        return _Loc(sel, self)

    def query_selector(self, sel):
        if "decision-current" in sel:                # the hero-is-current-actor turn check
            return object() if self.my_turn else None
        return None

    def query_selector_all(self, sel):
        if "button" in sel and self.my_turn:         # real turn -> an amount-bearing control exists
            return [_Marker()]
        return []


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


def test_does_not_act_when_not_heros_turn():
    # the one-street-lag bug: if the turn already passed, the on-screen controls are PRE-ACTION
    # (queued for next turn). The executor must click NOTHING when it isn't the current actor.
    page = _Page(my_turn=False)
    assert _ex(page).execute(Decision(ActionType.BET, D("90"), "bet")) is False
    assert _ex(page).execute(Decision(ActionType.CHECK, D("0"), "check")) is False
    assert page.clicked == []


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
                if kind == "confirm" and (not self.page.panel_open or self.page.no_submit):
                    raise RuntimeError("no confirm")
                if kind in ("check", "call") and self.page.panel_open:
                    # REALISTIC: the open bet panel REPLACES check/call/fold on the live table
                    raise RuntimeError("hidden by the open bet panel")
                self.page.click_kind(kind)
                return
        raise RuntimeError("miss")


class _BetPage:
    """Models PokerNow's bet panel: opens with a MIN default; settable via slider/native; presets
    set a pot fraction; confirm commits whatever is in the box. While the panel is open the
    check/call buttons are HIDDEN (replaced by presets + BACK), exactly like the real table."""

    def __init__(self, *, settable=True, presets=True, pot=200.0, minbet=2.0,
                 no_submit=False, reselect_breaks=False, panel_never_opens=False):
        self.settable, self.presets, self.pot, self.minbet = settable, presets, pot, minbet
        self.no_submit = no_submit              # the confirm submit is broken/unfindable
        self.reselect_breaks = reselect_breaks  # preset clicks stop registering after the 4 probes
        self.panel_never_opens = panel_never_opens   # the RAISE control is a pre-action toggle
        self.preset_clicks = 0
        self.raise_clicks = 0
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
            self.raise_clicks += 1
            if self.panel_never_opens:                           # a pre-action toggle: no panel
                return
            self.panel_open, self.amount = True, self.minbet     # opens with the min default
        elif kind == "confirm" and self.panel_open and self.amount is not None:
            self.confirmed, self.panel_open = self.amount, False
        elif kind == "BACK":
            self.panel_open = False                              # closes the panel (no confirm)
        elif kind in ("check", "call", "fold"):
            self.actions.append(kind)
        elif kind.upper().endswith("POT") or kind.upper() == "ALL IN":
            self.preset_clicks += 1
            if self.reselect_breaks and self.preset_clicks > 4:
                return                                           # the re-select silently misses
            frac = {"1/2 POT": 0.5, "3/4 POT": 0.75, "POT": 1.0, "ALL IN": 99}.get(kind.upper())
            if frac and self.panel_open:
                self.amount = self.pot * frac if frac < 90 else self.pot * 5

    def locator(self, sel):
        return _BetLoc(sel, self)

    def query_selector(self, sel):
        if "decision-current" in sel:
            return _BetEl("turn", self)              # it's the hero's turn in these tests
        if "submit" in sel:
            return _BetEl("confirm", self) if (self.panel_open and not self.no_submit) else None
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
        if "button" in sel:
            els = [_Marker()]                        # an amount-bearing control: it IS a real turn
            if self.panel_open:                      # the panel's own controls: presets + BACK
                els += [_BetEl(t, self)
                        for t in (("1/2 POT", "3/4 POT", "POT", "ALL IN") if self.presets else ())]
                els += [_BetEl("BACK", self)]
            return els
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


def test_preset_fallback_picks_closest_not_an_overbet():
    # the 152->230 leak: target is ½-pot but the fallback grabbed ¾-pot. Must pick the CLOSEST preset.
    page = _BetPage(settable=False, presets=True, pot=304.0)   # ½pot=152, ¾pot=228, pot=304
    assert _ex(page).execute(Decision(ActionType.BET, D("152.00"), "value bet")) is True
    assert page.confirmed is not None and abs(page.confirmed - 152.0) <= 1   # ½-pot, not ¾-pot (228)


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


def test_small_target_never_accepts_the_min_default():
    # tolerance bug: target 2.00 with the panel's 1.00 min default must NOT verify — the old flat
    # ±2.0 allowance accepted it, silently confirming a min bet as "2.00".
    page = _BetPage(settable=False, presets=False, pot=4.0, minbet=1.0)
    assert _ex(page).execute(Decision(ActionType.BET, D("2.00"), "small value bet")) is True
    assert page.confirmed is None        # never confirmed the 1.00 default as if it were 2.00
    assert page.actions == ["check"]


def test_confirm_fallback_never_clicks_the_all_in_preset():
    # confirm bug: the submit is broken; the old text-fallback matched the ALL IN preset (a real
    # <button> in the panel) and "confirmed" by RE-SIZING the bet to a jam. Now: no confirm ->
    # close the panel -> take the free check. The box must never be left re-sized to all-in.
    page = _BetPage(settable=True, presets=True, pot=200.0, no_submit=True)
    assert _ex(page).execute(Decision(ActionType.BET, D("150.00"), "value bet")) is True
    assert page.confirmed is None
    assert page.actions == ["check"]
    assert page.amount != 200.0 * 5      # never left sitting on the ALL-IN amount


def test_preset_reselect_is_verified_never_a_jam():
    # re-select bug: probing the presets ends on ALL IN; if re-selecting the closest one doesn't
    # stick, the box still holds the jam — the old code confirmed it (accidental all-in).
    page = _BetPage(settable=False, presets=True, pot=200.0, reselect_breaks=True)
    assert _ex(page).execute(Decision(ActionType.BET, D("100.00"), "half pot")) is True
    assert page.confirmed is None        # never confirmed the stuck ALL-IN amount
    assert page.actions == ["check"]


def test_pre_action_lookalikes_are_never_clicked():
    # live bug: right after the hero acts, PokerNow LEAVES `.decision-current` on the hero seat
    # and shows amount-less pre-action RAISE/CHECK/FOLD toggles. Clicking them queues an action
    # that fires NEXT turn at the remembered amount (the 'turn lead = flop lead' disconnect).
    # With no real-turn marker (no amounts, no panel, no YOUR TURN) the executor must refuse.
    class _StaleTurnPage:
        def __init__(self):
            self.clicked = []

        def query_selector(self, sel):
            return object() if "decision-current" in sel else None

        def query_selector_all(self, sel):
            if "button" in sel:
                return [_Marker("RAISE"), _Marker("CHECK"), _Marker("FOLD")]  # amount-less toggles
            return []

        def locator(self, sel):
            raise AssertionError(f"clicked {sel} during a fake turn")

    page = _StaleTurnPage()
    assert _ex(page).execute(Decision(ActionType.BET, D("60"), "turn lead")) is False
    assert _ex(page).execute(Decision(ActionType.CHECK, D("0"), "check")) is False
    assert page.clicked == []


def test_raise_click_without_a_panel_is_unqueued_and_aborted():
    # the RAISE control turned out to be a pre-action toggle (no panel appeared): the executor
    # must click it AGAIN to un-queue the stale raise, then walk away — never fall back to
    # check/call (those would queue more pre-actions).
    page = _BetPage(panel_never_opens=True, pot=200.0)
    assert _ex(page).execute(Decision(ActionType.BET, D("60.00"), "turn lead")) is False
    assert page.raise_clicks == 2        # queue + un-queue
    assert page.confirmed is None        # nothing was ever confirmed
    assert page.actions == []            # and no check/call was clicked


def test_fallback_closes_the_panel_before_checking():
    # panel bug: with the panel open, check/call are HIDDEN (this fake now enforces it, like the
    # real table) — the couldn't-size fallback must close the panel via BACK or its click misses.
    page = _BetPage(settable=False, presets=False, pot=200.0)
    assert _ex(page).execute(Decision(ActionType.BET, D("150.00"), "value bet")) is True
    assert page.panel_open is False      # BACK was clicked
    assert page.actions == ["check"]     # ... and then the check landed
