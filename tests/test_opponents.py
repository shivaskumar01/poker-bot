from pokerbot.opponents.classify import classify
from pokerbot.opponents.stats import PlayerStats, Stat
from pokerbot.opponents.store import StatsStore
from pokerbot.strategy import exploit


def make(name, hands, vpip, pfr, agg, call, **extra):
    ps = PlayerStats(name=name, hands=hands, agg_actions=agg, call_actions=call)
    ps.vpip = Stat(int(vpip * hands), hands)
    ps.pfr = Stat(int(pfr * hands), hands)
    for k, v in extra.items():
        setattr(ps, k, v)
    return ps


def test_shrinkage_pulls_small_samples_to_prior():
    assert abs(Stat(5, 10).shrunk(0.2, 20) - 0.3) < 1e-9   # (5 + 4) / (10 + 20)
    assert Stat(0, 0).shrunk(0.25, 20) == 0.25             # no data -> prior exactly


def test_confidence_scales_with_hands():
    assert PlayerStats("a", hands=0).confidence == 0.0
    assert PlayerStats("b", hands=30).confidence == 0.5
    assert PlayerStats("c", hands=600).confidence == 1.0


def test_classify_archetypes():
    assert classify(make("n", 200, 0.10, 0.08, 10, 5)) == "nit"
    assert classify(make("s", 200, 0.45, 0.05, 5, 60)) == "station"
    assert classify(make("m", 200, 0.55, 0.45, 200, 10)) == "maniac"
    assert classify(make("t", 200, 0.22, 0.18, 60, 25)) == "tag"
    assert classify(make("l", 200, 0.33, 0.26, 90, 30)) == "lag"
    assert classify(PlayerStats("u", hands=5)) == "unknown"


def test_store_roundtrip_preserves_counters():
    store = StatsStore(":memory:")
    ps = make("villain", 100, 0.30, 0.20, 40, 20)
    ps.threebet = Stat(7, 95)
    store.save(ps)
    got = store.get("villain")
    assert got.hands == 100
    assert got.agg_actions == 40 and got.call_actions == 20
    assert got.threebet.made == 7 and got.threebet.opp == 95
    assert classify(got) == classify(ps)
    assert store.get("never-seen").hands == 0   # unknown player -> fresh stats
    store.close()


def test_exploit_adjustments_are_directional():
    station = make("s", 200, 0.45, 0.05, 5, 60)
    nit = make("n", 200, 0.10, 0.08, 10, 5)
    maniac = make("m", 200, 0.55, 0.45, 200, 10)

    assert exploit.adj_value_threshold(0.55, station) < 0.55   # value bet thinner
    assert exploit.adj_value_threshold(0.55, nit) > 0.55       # tighter vs nit
    assert exploit.adj_call_required(0.50, maniac) < 0.50      # call lighter vs over-bluffer
    assert exploit.adj_bluff_freq(0.40, station) < 0.40        # don't bluff stations

    _, cont_vs_maniac = exploit.adj_vs_raise(0.06, 0.20, maniac)
    _, cont_vs_nit = exploit.adj_vs_raise(0.06, 0.20, nit)
    assert cont_vs_maniac > 0.20 > cont_vs_nit                 # defend wider vs maniac

    # no read (or too few hands) -> baseline unchanged
    assert exploit.adj_value_threshold(0.55, None) == 0.55
    assert exploit.adj_call_required(0.50, PlayerStats("x", hands=3)) == 0.50


def test_call_required_is_person_driven():
    # bluff-catch by PERSON: call lighter vs aggressive bluffers, tighter vs passive value-bettors
    station = make("s", 200, 0.45, 0.05, 5, 60)
    nit = make("n", 200, 0.10, 0.08, 10, 5)
    lag = make("l", 200, 0.33, 0.26, 120, 40)
    maniac = make("m", 200, 0.55, 0.45, 200, 10)
    base = 0.50
    assert exploit.adj_call_required(base, maniac) < exploit.adj_call_required(base, lag) < base
    assert exploit.adj_call_required(base, station) > base
    assert exploit.adj_call_required(base, nit) > exploit.adj_call_required(base, station)
