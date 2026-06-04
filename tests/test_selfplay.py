from pokerbot.runtime.selfplay import engine_agent, run, station_agent


def test_chips_conserved_homogeneous():
    res = run(num_hands=120, players=3, seed=3, iterations=120, learn=False)
    assert res["hands"] == 120
    assert res["total_net"] == 0          # zero-sum: pokerkit pots create/destroy no chips


def test_bot_beats_calling_stations():
    agents = {0: engine_agent, 1: station_agent, 2: station_agent}
    res = run(num_hands=400, players=3, seed=7, iterations=150, learn=False,
              agents_by_stable=agents)
    assert res["total_net"] == 0
    assert res["bb_per_100"]["P0"] > 0     # the real strategy must beat pure calling-stations


def test_learning_path_populates_stats():
    res = run(num_hands=60, players=6, seed=1, iterations=80, learn=True)
    assert len(res["stats"]) == 6
    assert all(ps.hands > 0 for ps in res["stats"].values())
