from decimal import Decimal as D

from pokerbot.io.scraper import RawObservation, RawSeat
from pokerbot.model.state import ActionType
from pokerbot.runtime.config import Config
from pokerbot.runtime.orchestrator import LiveBot
from pokerbot.runtime.safety import Limits, SessionGuard


def _cfg(mode="observe", consent=False):
    return Config(mode=mode, players_consent=consent, table_url="", small_blind=D("0.5"),
                  big_blind=D("1"), ante=D("0"), buy_in=D("100"), hero_name=None, stop_loss_bb=200,
                  stop_win_bb=400, max_hands=500, mc_iterations=300, mc_iterations_big_pot=9000,
                  min_think=0.0, max_think=0.0, max_action_wait=6.0, db_path=":none:",
                  hand_log_path="", kill_file="STOP")


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

    def activate_extra_time(self):
        return False

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
    return SessionGuard(Limits(200, 400, 500), D("1"))


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


def test_latch_no_phantom_redecide_after_own_raise():
    # The "dashboard says 20 but bet 26" bug: after our raise registers, to-call drops (here 20->0)
    # while it's BRIEFLY still our turn (DOM lag). The loop must NOT re-decide the same hand to a
    # fresh (random-sized) raise and push that phantom to the dashboard after the bet already landed.
    import threading
    stop = threading.Event()

    facing = RawObservation(                              # pocket aces facing an open to 3 -> 3-bet
        seats=[RawSeat(0, "hero", "100", is_hero=True, cards=["Ac", "Ad"]),
               RawSeat(1, "vik", "100")],
        board=[], pot="4.5", to_call="3", button_seat_id=0)
    after = RawObservation(                               # our 3-bet registered: to-call now 0
        seats=[RawSeat(0, "hero", "91", is_hero=True, cards=["Ac", "Ad"]),
               RawSeat(1, "vik", "100")],
        board=[], pot="13.5", to_call="0", button_seat_id=0)

    class _Scr:
        page = None
        def __init__(self):
            self.turn_calls = 0
            self.reads = 0

        def read_blinds(self):
            return None

        def read_hero_stack(self):
            return None

        def read_seconds_left(self):
            return None

        def action_buttons_present(self):
            return False

        def is_hero_turn(self):
            self.turn_calls += 1
            if self.turn_calls >= 12:
                stop.set()                                # end the loop after enough polls
            return self.turn_calls <= 5                   # still our turn (lag) for a bit, then passes

        def read_observation(self):
            self.reads += 1
            return facing if self.reads == 1 else after

    import random
    seen = []
    ex = _RecExec(can_act=True)
    bot = LiveBot(_Scr(), ex, None, _cfg("execute", True), _guard(), rng=random.Random(0),
                  on_decision=lambda gs, d, reads, secs=None: seen.append(d), stop_event=stop)
    bot.run()

    assert len(ex.calls) == 1                             # acted exactly once
    assert ex.calls[0].action == ActionType.RAISE        # a value 3-bet (mixed-size -> the phantom risk)
    assert len(seen) == 1                                 # dashboard shown ONE decision (no phantom)
    assert seen[0] is ex.calls[0]                         # the shown decision IS the executed one (same
    #                                                      object) -> dashboard amount == bet amount, always


def test_latch_rearms_on_new_street_when_first_to_act():
    # The regression the latch introduced: after we CLOSE a street (call preflop) and are first to
    # act on the flop, there may be NO opponent turn in between, so is_hero_turn never reads False.
    # The latch must still re-arm on the new street (board changed) so the bot acts on the flop.
    import random
    import threading
    stop = threading.Event()

    preflop = RawObservation(                             # hero is BB (opp on button) facing an open
        seats=[RawSeat(0, "hero", "100", is_hero=True, cards=["Ac", "Ad"]),
               RawSeat(1, "vik", "100")],
        board=[], pot="4.5", to_call="3", button_seat_id=1)
    flop = RawObservation(                                # flop dealt; hero (OOP) is first to act
        seats=[RawSeat(0, "hero", "94", is_hero=True, cards=["Ac", "Ad"]),
               RawSeat(1, "vik", "94")],
        board=["Kc", "7d", "2s"], pot="12", to_call="0", button_seat_id=1)

    class _Scr:
        page = None

        def __init__(self):
            self.reads = 0

        def read_blinds(self):
            return None

        def read_hero_stack(self):
            return None

        def read_seconds_left(self):
            return None

        def action_buttons_present(self):
            return False

        def is_hero_turn(self):
            return True                                   # WORST CASE: never reads False between streets

        def read_observation(self):
            self.reads += 1
            if self.reads >= 6:
                stop.set()
            return preflop if self.reads <= 2 else flop

    seen = []
    ex = _RecExec(can_act=True)
    bot = LiveBot(_Scr(), ex, None, _cfg("execute", True), _guard(), rng=random.Random(0),
                  on_decision=lambda gs, d, reads, secs=None: seen.append(gs.street.name),
                  stop_event=stop)
    bot.run()

    assert seen == ["PREFLOP", "FLOP"]                    # acted on BOTH streets, exactly once each
    assert len(ex.calls) == 2                             # ... and clicked both (no skipped flop)
    assert bot.guard.hands == 1                           # two decisions, ONE hand (same hole cards)


def test_hand_counted_even_when_first_decision_faces_a_raise():
    # the under-count: hero's FIRST preflop decision faces a raise (to_call > bb), the old
    # `to_call <= bb` proxy skipped these hands entirely, so max_hands/the display drifted low.
    import random
    import threading
    stop = threading.Event()

    facing = RawObservation(
        seats=[RawSeat(0, "hero", "100", is_hero=True, cards=["Ac", "Ad"]),
               RawSeat(1, "vik", "100")],
        board=[], pot="4.5", to_call="3", button_seat_id=1)

    class _Scr:
        page = None

        def __init__(self):
            self.polls = 0

        def read_blinds(self):
            return None

        def read_hero_stack(self):
            return None

        def read_seconds_left(self):
            return None

        def action_buttons_present(self):
            return False

        def is_hero_turn(self):
            self.polls += 1
            if self.polls >= 4:
                stop.set()
            return True

        def read_observation(self):
            return facing

    bot = LiveBot(_Scr(), _RecExec(False), None, _cfg(), _guard(), rng=random.Random(0),
                  stop_event=stop)
    bot.run()
    assert bot.guard.hands == 1                           # counted despite facing a raise


def test_big_pots_use_more_mc_iterations():
    # mc_iterations_big_pot must actually be wired: >=40bb pots get the big rollout count
    import pokerbot.runtime.orchestrator as orch

    seen_iters = []
    real_decide = orch.decide

    def spy(gs, rng, iterations, reads=None):
        seen_iters.append(iterations)
        return real_decide(gs, rng, 50, reads=reads)

    small = RawObservation(
        seats=[RawSeat(0, "hero", "100", is_hero=True, cards=["As", "Ad"]),
               RawSeat(1, "vik", "100")],
        board=["As", "7c", "2d"], pot="6", to_call="0", button_seat_id=0)
    big = RawObservation(
        seats=[RawSeat(0, "hero", "100", is_hero=True, cards=["As", "Ad"]),
               RawSeat(1, "vik", "100")],
        board=["As", "7c", "2d"], pot="80", to_call="0", button_seat_id=0)

    orig = orch.decide
    orch.decide = spy
    try:
        bot = LiveBot(_FakeScraper(small), _RecExec(False), None, _cfg(), _guard())
        bot.step()
        bot2 = LiveBot(_FakeScraper(big), _RecExec(False), None, _cfg(), _guard())
        bot2.step()
    finally:
        orch.decide = orig
    assert seen_iters == [300, 9000]                      # base for 6bb, big for 80bb


def test_refused_execute_re_decides_on_the_real_turn():
    # the pre-action fix refuses to click when the controls aren't live. The orchestrator must
    # then re-DECIDE the same spot on the real turn (identical sig!) instead of skipping it as
    # a duplicate, otherwise the bot freezes on its real turn and gets auto-folded.
    import random
    import threading
    stop = threading.Event()

    class _FlakyExec:
        def __init__(self):
            self.attempts = 0
            self.landed = []

        @property
        def can_act(self):
            return True

        def activate_extra_time(self):
            return False

        def execute(self, decision):
            self.attempts += 1
            if self.attempts == 1:
                return False              # controls weren't live (pre-action window)
            self.landed.append(decision)
            return True

    class _Scr:
        page = None

        def __init__(self):
            self.t = 0

        def read_blinds(self):
            return None

        def read_hero_stack(self):
            return None

        def read_seconds_left(self):
            return None

        def action_buttons_present(self):
            return False

        def is_hero_turn(self):
            self.t += 1
            if self.t >= 14:
                stop.set()
            return self.t != 3            # one not-my-turn tick between the two attempts

        def read_observation(self):
            return _RAW                   # IDENTICAL observation both times (same sig)

    seen = []
    ex = _FlakyExec()
    bot = LiveBot(_Scr(), ex, None, _cfg("execute", True), _guard(), rng=random.Random(0),
                  on_decision=lambda gs, d, reads, secs=None: seen.append(d), stop_event=stop)
    bot.run()
    assert len(seen) == 2                 # decided again on the real turn (sig re-armed)
    assert len(ex.landed) == 1            # and the action landed exactly once


def test_table_check_surfaces_errors_as_warnings():
    class _Boom:
        def read_blinds(self):
            raise RuntimeError("selector vanished")

        def read_hero_stack(self):
            return None

    status = {}
    bot = LiveBot(_Boom(), _RecExec(False), None, _cfg(), _guard(),
                  on_status=lambda d: status.update(d))
    bot._table_check()
    assert "selector vanished" in (status.get("warning") or "")   # surfaced to the UI, not just stdout
    ok = _TableScraper((D("0.5"), D("1")), D("100"))
    bot.scraper = ok
    bot._table_check()
    assert status["warning"] is None                              # clears once upkeep succeeds


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


class _TableScraper:
    """Fake supporting the out-of-turn table check (auto blinds + hero stack)."""

    def __init__(self, blinds, stack):
        self.blinds = blinds
        self.stack = stack

    def read_blinds(self):
        return self.blinds

    def read_hero_stack(self):
        return self.stack


def test_table_check_autodetects_changing_blinds():
    sc = _TableScraper((D("1"), D("2")), D("150"))
    g = _guard()
    status = {}
    bot = LiveBot(sc, _RecExec(False), None, _cfg(), g, on_status=lambda d: status.update(d))
    bot._table_check()
    assert bot.config.small_blind == D("1") and bot.config.big_blind == D("2")
    assert g.bb == D("2")                              # stop-loss now measured in the new bb
    assert status["needs_rebuy"] is False and status["stack"] == "150"


def test_sustained_zero_stack_is_a_bust():
    sc = _TableScraper((D("0.5"), D("1")), D("0"))     # bot is stacked
    g = _guard()
    g.observe_bankroll(D("100"))
    bot = LiveBot(sc, _RecExec(True), None, _cfg("execute", True), g)
    for _ in range(3):
        bot._table_check()
        assert bot._needs_rebuy is False               # debounced, not flagged on a brief 0
    bot._table_check()                                 # 4th sustained 0
    assert bot._needs_rebuy is True
    bot.request_rebuy()                                # user tops up + confirms
    sc.stack = D("100")
    bot._table_check()
    assert bot._needs_rebuy is False
    assert g.start == D("100") and g.net_bb == 0.0     # fresh baseline after the second buy-in


def test_allin_zero_then_win_is_not_a_bust():
    # going all-in shows a 0 stack for a moment; winning the pot restores it -> must NOT bust
    sc = _TableScraper((D("0.5"), D("1")), D("200"))
    g = _guard()
    g.observe_bankroll(D("200"))
    bot = LiveBot(sc, _RecExec(True), None, _cfg("execute", True), g)
    sc.stack = D("0")
    bot._table_check(); bot._table_check()             # all-in: stack reads 0 briefly
    assert bot._needs_rebuy is False                   # not yet (debounced)
    sc.stack = D("400")                                # won the pot, stacked the opponent
    bot._table_check()
    assert bot._needs_rebuy is False                   # decisively not busted
    assert g.net_bb > 0                                # bankroll reflects the win, not a phantom 0


def test_kill_switch(tmp_path):
    kf = tmp_path / "STOP"
    kf.write_text("x")
    g = SessionGuard(Limits(200, 400, 500), D("1"), kill_file=str(kf))
    stop, why = g.should_stop()
    assert stop and "kill" in why


def test_own_open_makes_the_next_decision_a_3bet_pot():
    # the mis-route: bot opens to 3, villain 3-bets to 9 (CALL 6). Without tracking its own
    # raise, the bot re-reconstructed hero committed = the 0.5 blind (pot 7, not 12) and saw
    # ONE raise (an "open") -> 4-bet way too wide. With _pre_track it must see a 3-BET pot.
    from pokerbot.model.state import Street
    bot = LiveBot(_FakeScraper(None), _RecExec(True), None, _cfg("execute", True), _guard())
    bot._pre_track = (("Ac", "Ad"), 1, D("3"))            # we opened to 3 with AcAd
    raw = RawObservation(
        seats=[RawSeat(0, "hero", "97", is_hero=True, cards=["Ac", "Ad"]),
               RawSeat(1, "vik", "91")],
        board=[], pot="0", to_call="6", button_seat_id=0)  # hero BTN/SB, villain BB 3-bet to 9
    gs = bot._build_state(raw)
    assert gs.street == Street.PREFLOP
    assert gs.hero.committed == D("3")                    # our open survived reconstruction
    assert gs.seat(1).committed == D("9")                 # villain's 3-bet total = 3 + CALL 6
    assert gs.pot == D("12")                              # true pot -> true price (6/18, not 6/13)
    raises = [a for a in gs.actions if a.action == ActionType.RAISE]
    assert len(raises) == 2                               # open + 3-bet -> routed to _vs_3bet
    assert raises[-1].seat_id == 1                        # the villain is the aggressor

    # different hole cards = a NEW hand: the stale track must not leak into it
    fresh = RawObservation(
        seats=[RawSeat(0, "hero", "100", is_hero=True, cards=["7c", "2d"]),
               RawSeat(1, "vik", "97")],
        board=[], pot="0", to_call="2.5", button_seat_id=1)
    gs2 = bot._build_state(fresh)
    raises2 = [a for a in gs2.actions if a.action == ActionType.RAISE]
    assert len(raises2) == 1                              # plain open faced, hero blind restored
    assert gs2.hero.committed == D("1")                   # BB, not the stale 3


def test_config_loads_big_pot_iterations(tmp_path):
    from pokerbot.runtime.config import load_config
    p = tmp_path / "config.yaml"
    p.write_text("engine:\n  mc_iterations: 1500\n  mc_iterations_big_pot: 60000\n")
    cfg = load_config(str(p))
    assert cfg.mc_iterations == 1500
    assert cfg.mc_iterations_big_pot == 60000
    assert load_config(str(p)).max_hands == 500          # untouched keys keep their defaults
