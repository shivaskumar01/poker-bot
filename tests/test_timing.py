import random
import re
from decimal import Decimal as D
from types import SimpleNamespace as NS

from pokerbot.model.state import ActionType, Street
from pokerbot.strategy.timing import think_seconds, tempo_label


def _d(action=ActionType.CALL, equity=0.5):
    return NS(action=action, equity=equity, amount=D("0"))


def _gs(street=Street.FLOP, to_call=D("2"), stack=D("100")):
    return NS(street=street, to_call=to_call, hero=NS(stack=stack))


def test_timing_disabled_when_hi_zero():
    # headless/tests pass min=max=0 -> never sleep
    assert think_seconds(_d(), _gs(), random.Random(0), lo=0, hi=0) == 0.0


def test_timing_positive_and_within_cap():
    rng = random.Random(1)
    cap = max(6.0 * 2.2, 12.0)
    vals = [think_seconds(_d(), _gs(), rng, lo=1.5, hi=6.0) for _ in range(500)]
    assert all(0.3 <= v <= cap for v in vals)


def test_timing_produces_snaps_and_tanks_even_on_strong_hands():
    # a strong value raise still both snaps AND tanks across samples -> the clock can't be used
    # to read hand strength (a tank-raise with the nuts looks like a tank-bluff)
    rng = random.Random(2)
    strong = [think_seconds(_d(ActionType.RAISE, 0.92), _gs(Street.RIVER), rng, lo=1.5, hi=6.0)
              for _ in range(800)]
    assert min(strong) <= 1.0          # snaps occur
    assert max(strong) >= 6.0          # tanks occur


def test_tempo_label():
    assert tempo_label(None) == ""
    assert tempo_label(0.6).startswith("snap")
    assert tempo_label(9.0, hi=6.0).startswith("tank")
    assert re.fullmatch(r"3s", tempo_label(3.0, hi=6.0))
