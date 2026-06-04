from decimal import Decimal as D

from pokerbot.io.scraper import RawObservation, RawSeat
from pokerbot.model.state import ActionType
from pokerbot.runtime.config import Config
from pokerbot.runtime.orchestrator import LiveBot
from pokerbot.runtime.safety import Limits, SessionGuard


def _cfg(mode="observe", consent=False):
    return Config(mode=mode, players_consent=consent, table_url="", small_blind=D("0.5"),
                  big_blind=D("1"), ante=D("0"), hero_name=None, stop_loss_bb=200, stop_win_bb=400,
                  max_hands=500, mc_iterations=300, min_think=0.0, max_think=0.0,
                  db_path=":none:", hand_log_path="", kill_file="STOP")


class _FakeScraper:
    def __init__(self, raw):
        self.raw = raw

    def is_hero_turn(self):
        return True

    def read_observation(self):
        return self.raw


class _RecExec:
    def __init__(self, can_act):
        self._can = can_act
        self.calls = []

    @property
    def can_act(self):
        return self._can

    def execute(self, decision):
        self.calls.append(decision)
        return True


# AA set on A72, checked to -> a clear value bet
_RAW = RawObservation(
    seats=[RawSeat(0, "hero", "100", is_hero=True, cards=["As", "Ad"]),
           RawSeat(1, "vik", "100")],
    board=["As", "7c", "2d"], pot="6", to_call="0", button_seat_id=0,
)


def _guard():
    return SessionGuard(Limits(200, 400, 500), D("1"), think=(0.0, 0.0))


def test_observe_mode_decides_but_never_executes():
    ex = _RecExec(can_act=False)
    bot = LiveBot(_FakeScraper(_RAW), ex, None, _cfg("observe", False), _guard())
    _gs, d, acted = bot.step()
    assert d.action == ActionType.BET     # AA trips value-bets
    assert acted is False and ex.calls == []


def test_execute_mode_with_consent_acts():
    ex = _RecExec(can_act=True)
    bot = LiveBot(_FakeScraper(_RAW), ex, None, _cfg("execute", True), _guard())
    _gs, d, acted = bot.step()
    assert acted is True and ex.calls == [d]


def test_session_guard_stop_loss_and_win():
    g = SessionGuard(Limits(50, 100, 1000), D("1"))
    g.observe_bankroll(D("200"))
    assert g.should_stop()[0] is False
    g.observe_bankroll(D("145"))          # -55bb
    stop, why = g.should_stop()
    assert stop and "stop-loss" in why
    g2 = SessionGuard(Limits(50, 100, 1000), D("1"))
    g2.observe_bankroll(D("200"))
    g2.observe_bankroll(D("305"))         # +105bb
    assert "stop-win" in g2.should_stop()[1]


def test_session_guard_max_hands():
    g = SessionGuard(Limits(200, 400, 2), D("1"))
    g.count_hand()
    g.count_hand()
    assert g.should_stop()[0] and "max hands" in g.should_stop()[1]


def test_kill_switch(tmp_path):
    kf = tmp_path / "STOP"
    kf.write_text("x")
    g = SessionGuard(Limits(200, 400, 500), D("1"), kill_file=str(kf))
    stop, why = g.should_stop()
    assert stop and "kill" in why
