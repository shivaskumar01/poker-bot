from pokerbot.opponents.classify import classify
from pokerbot.opponents.stats import PlayerStats, Stat


def _ps(vpip, pfr, agg, call, hands=400, hu=False):
    ps = PlayerStats(name="x#hu" if hu else "x", hands=hands, heads_up=hu,
                     agg_actions=agg, call_actions=call)
    ps.vpip = Stat(made=int(vpip * hands), opp=hands)
    ps.pfr = Stat(made=int(pfr * hands), opp=hands)
    return ps


def test_same_stats_classify_differently_by_table_size():
    # loose-aggressive numbers: a LAG at a full table, but only a TAG by heads-up standards
    assert classify(_ps(0.38, 0.26, 30, 10, hu=False)) == "lag"
    assert classify(_ps(0.38, 0.26, 30, 10, hu=True)) == "tag"


def test_heads_up_loose_is_not_a_maniac():
    # VPIP 50 / AF>4 is a maniac at a full table but normal heads-up
    assert classify(_ps(0.50, 0.40, 50, 8, hu=False)) == "maniac"
    assert classify(_ps(0.50, 0.40, 50, 8, hu=True)) != "maniac"


def test_store_marks_hu_profiles(tmp_path):
    from pokerbot.opponents.store import StatsStore
    s = StatsStore(str(tmp_path / "o.sqlite"))
    assert s.get("bizz").heads_up is False
    assert s.get("bizz#hu").heads_up is True
