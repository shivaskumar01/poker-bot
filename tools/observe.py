"""READ-ONLY live observe — watch the bot read your PokerNow table and narrate decisions.

It NEVER clicks (the executor isn't even imported). Whenever it's your turn, it scrapes the
table, builds a GameState, and prints the move it *would* make + equity + rationale, so you
can confirm it's reading correctly before any execute-mode bring-up.

    PYTHONPATH=src ./.venv/bin/python tools/observe.py "<table-url>" [--sb 0.5] [--bb 1] [--hero NAME]
"""
from __future__ import annotations

import os
import random
import sys
import time
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pokerbot.io.browser import Browser              # noqa: E402
from pokerbot.io.scraper import Scraper, to_game_state  # noqa: E402
from pokerbot.io.selectors import Selectors          # noqa: E402
from pokerbot.strategy.engine import decide           # noqa: E402


def _opt(flag: str, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main() -> None:
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = pos[0] if pos else input("PokerNow table URL: ").strip()
    sb, bb = Decimal(str(_opt("--sb", "0.5"))), Decimal(str(_opt("--bb", "1")))
    hero = _opt("--hero", None)

    browser = Browser(profile_dir=os.path.expanduser("~/.pokerbot-profile"))
    page = browser.open(url)
    input("\n>> Join/observe the table, then press Enter to start READ-ONLY watching...")
    scraper = Scraper(page, Selectors(), hero_name=hero)
    rng = random.Random()
    print(f"\nwatching (blinds {sb}/{bb}, READ-ONLY, Ctrl-C to stop)...\n")

    last = None
    try:
        while True:
            if scraper.is_hero_turn():
                try:
                    gs = to_game_state(scraper.read_observation(), sb, bb)
                    sig = (tuple(map(str, gs.hero.cards)), tuple(map(str, gs.board)), str(gs.to_call))
                    if sig != last:
                        last = sig
                        d = decide(gs, rng, iterations=3000)
                        hole = " ".join(map(str, gs.hero.cards)) or "??"
                        board = " ".join(map(str, gs.board)) or "-"
                        amt = f" {d.amount}" if d.action.name in ("BET", "RAISE") else ""
                        eq = f" eq={d.equity:.2f}" if d.equity is not None else ""
                        print(f"[{gs.street.name}] {hole} | board {board} | pos {gs.hero_position} "
                              f"| {gs.num_live_opponents} opp | pot {gs.pot} to-call {gs.to_call}")
                        print(f"   => WOULD {d.action.name}{amt}{eq}   {d.rationale}\n")
                except Exception as e:  # noqa: BLE001 - keep watching through transient read errors
                    print("read error:", e)
                time.sleep(2)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nstopped.")
        browser.close()


if __name__ == "__main__":
    main()
