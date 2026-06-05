"""Read PokerNow logs, learn HUD stats for every player, print a report, persist to SQLite.

    PYTHONPATH=src ./.venv/bin/python tools/analyze_logs.py ["~/Desktop/Poker learning logs"]
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pokerbot.io.log_parser import parse_file          # noqa: E402
from pokerbot.opponents.classify import classify        # noqa: E402
from pokerbot.opponents.store import StatsStore          # noqa: E402
from pokerbot.opponents.tracking import accumulate, merge_aliases  # noqa: E402

# Real friend-group games only. The "Poker test" logs are bot-vs-self (the seat labeled
# "vik" there is the user's own account), so they'd corrupt the real opponents' profiles.
DEFAULT_FOLDERS = [os.path.expanduser("~/Desktop/Poker learning logs")]


def cell(stat) -> str:
    r = stat.raw
    return f"{r * 100:3.0f}% /{stat.opp:<4d}" if r is not None else f"  -- /{stat.opp:<4d}"


def main() -> None:
    if len(sys.argv) > 1:
        files = sorted(glob.glob(os.path.join(sys.argv[1], "*.csv")))
    else:
        files = sorted(f for d in DEFAULT_FOLDERS for f in glob.glob(os.path.join(d, "*.csv")))
    if not files:
        print(f"no CSV logs in {folder!r}")
        return

    stats: dict = {}
    total = 0
    for f in files:
        hands = parse_file(f)
        for h in hands:
            accumulate(stats, h)
        total += len(hands)
        print(f"  parsed {len(hands):4d} hands  <- {os.path.basename(f)}")
    stats = merge_aliases(stats)          # one profile per person (nicknames/ids/caps collapsed)
    print(f"\n{total} hands, {len(stats)} players\n")

    hdr = f"{'player':14s} {'hands':>5}  {'VPIP':>9} {'PFR':>9} {'3bet':>9} {'AF':>4}  {'Fc-bet':>9} {'WTSD':>9}  type"
    print(hdr)
    print("-" * len(hdr))
    for ps in sorted(stats.values(), key=lambda p: p.hands, reverse=True):
        print(f"{ps.name[:14]:14s} {ps.hands:5d}  {cell(ps.vpip):>9} {cell(ps.pfr):>9} "
              f"{cell(ps.threebet):>9} {ps.af:4.1f}  {cell(ps.fold_to_cbet_flop):>9} "
              f"{cell(ps.wtsd):>9}  {classify(ps)}")

    db_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(db_dir, exist_ok=True)
    store = StatsStore(os.path.join(db_dir, "opponents.sqlite"))
    store.clear()                         # full rebuild — drop stale/renamed rows first
    for ps in stats.values():
        store.save(ps)
    store.close()
    print(f"\nsaved {len(stats)} player profiles -> data/opponents.sqlite")
    print("(VPIP/PFR/3bet/Fc-bet/WTSD shown as rate / sample-size; AF = aggression factor)")


if __name__ == "__main__":
    main()
