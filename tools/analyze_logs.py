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
from pokerbot.opponents.tracking import build_profiles  # noqa: E402

# Real friend-group games only. The "Poker test" logs are bot-vs-self (the seat labeled
# "vik" there is the user's own account), so they'd corrupt the real opponents' profiles.
DEFAULT_FOLDERS = [os.path.expanduser("~/Desktop/Poker learning logs"),
                   os.path.expanduser("~/Desktop/Poker learning logs 2")]


def cell(stat) -> str:
    r = stat.raw
    return f"{r * 100:3.0f}% /{stat.opp:<4d}" if r is not None else f"  -- /{stat.opp:<4d}"


def main() -> None:
    folders = [sys.argv[1]] if len(sys.argv) > 1 else DEFAULT_FOLDERS
    files = sorted(f for d in folders for f in glob.glob(os.path.join(d, "*.csv")))
    if not files:
        print(f"no CSV logs in {folders}")
        return

    all_hands: list = []
    for f in files:
        hands = parse_file(f)
        all_hands += hands
        hu = sum(1 for h in hands if len(set(h.stacks) or {a.pid for a in h.actions}) == 2)
        print(f"  parsed {len(hands):4d} hands ({hu:4d} heads-up)  <- {os.path.basename(f)}")
    stats = build_profiles(all_hands)     # bucket by table size (HU 'name#hu' vs full/short-ring)
    print(f"\n{len(all_hands)} hands, {len(stats)} profiles "
          f"({sum(1 for n in stats if n.endswith('#hu'))} heads-up)\n")

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
    store.clear()                         # full rebuild, drop stale/renamed rows first
    for ps in stats.values():
        store.save(ps)
    store.close()
    print(f"\nsaved {len(stats)} player profiles -> data/opponents.sqlite")
    print("(VPIP/PFR/3bet/Fc-bet/WTSD shown as rate / sample-size; AF = aggression factor)")


if __name__ == "__main__":
    main()
