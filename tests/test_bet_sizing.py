from pokerbot.opponents.classify import classify
from pokerbot.strategy.exploit import bet_size_delta


class _Read:
    """Minimal stand-in with the fields classify() + bet_size_delta() use."""

    def __init__(self, hands, vpip, pfr, af, confidence):
        self.hands = hands
        self._v, self._p = vpip, pfr
        self.af = af
        self.confidence = confidence

    def r(self, k):
        return {"vpip": self._v, "pfr": self._p}.get(k, 0.0)


STATION = _Read(200, 0.50, 0.20, 1.5, 0.9)
MANIAC = _Read(200, 0.53, 0.41, 4.2, 0.9)


def test_archetypes_classify_as_expected():
    assert classify(STATION) == "station"
    assert classify(MANIAC) == "maniac"


def test_small_bets_get_no_read():
    assert bet_size_delta(0.5, MANIAC) == 0.0      # ~half pot: nothing to read
    assert bet_size_delta(0.7, STATION) == 0.0


def test_big_bet_reads_opposite_by_type():
    # an overbet from a maniac is often a bluff -> need LESS equity (call wider)
    assert bet_size_delta(1.2, MANIAC) < 0
    # an overbet from a station is value -> need MORE equity (fold more)
    assert bet_size_delta(1.2, STATION) > 0
    # bigger bet -> stronger read
    assert bet_size_delta(1.5, MANIAC) < bet_size_delta(1.0, MANIAC)


def test_low_confidence_is_neutral():
    assert bet_size_delta(1.5, None) == 0.0
    assert bet_size_delta(1.5, _Read(5, 0.5, 0.2, 1.5, 0.1)) == 0.0
