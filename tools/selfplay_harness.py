"""Bot-vs-bot self-play, validate the brain on full hands and measure bb/100.

    PYTHONPATH=src ./.venv/bin/python tools/selfplay_harness.py [hands] [players] [seed]
    PYTHONPATH=src ./.venv/bin/python tools/selfplay_harness.py 2000 3 1 --vs-stations

Default is homogeneous self-play (all seats the real engine; net should trend to ~0).
--vs-stations seats the real bot at P0 against calling-stations (P0 should win clearly).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pokerbot.opponents.classify import classify          # noqa: E402
from pokerbot.runtime.selfplay import (                    # noqa: E402
    engine_agent,
    run,
    station_agent,
)


def main() -> None:
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    hands = int(pos[0]) if len(pos) > 0 else 1000
    players = int(pos[1]) if len(pos) > 1 else 6
    seed = int(pos[2]) if len(pos) > 2 else 0
    vs_stations = "--vs-stations" in sys.argv

    agents = None
    if vs_stations:
        agents = {0: engine_agent}
        for i in range(1, players):
            agents[i] = station_agent

    mode = "P0 bot vs calling-stations" if vs_stations else "homogeneous self-play"
    print(f"running {hands} hands, {players}-handed, seed {seed}  ({mode})...")
    res = run(num_hands=hands, players=players, seed=seed, iterations=400,
              learn=not vs_stations, agents_by_stable=agents)

    print(f"chips conserved: sum(net) = {res['total_net']}")
    for i in range(players):
        print(f"  P{i}: {res['bb_per_100'][f'P{i}']:+8.1f} bb/100   (net {res['net'][i]:+d})")
    if res["stats"]:
        print("\nlearned from self-play:")
        for pid, ps in sorted(res["stats"].items()):
            print(f"  {pid}: {ps.hands:4d}h  VPIP {round((ps.vpip.raw or 0) * 100):3d}%  "
                  f"PFR {round((ps.pfr.raw or 0) * 100):3d}%  AF {ps.af:.1f}  -> {classify(ps)}")


if __name__ == "__main__":
    main()
