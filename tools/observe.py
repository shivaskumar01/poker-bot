"""READ-ONLY live observe — watch the bot read your PokerNow table and narrate decisions.

It NEVER clicks. It loads the learned opponent profiles (data/opponents.sqlite) and feeds
them to the engine, so the move it prints is the exploit-aware one. Whenever it's your turn
it prints the GameState + the move it *would* make + equity + which villain type it's
adjusting to.

    PYTHONPATH=src ./.venv/bin/python tools/observe.py "<table-url>" [--sb 0.5] [--bb 1] [--hero NAME]
"""
from __future__ import annotations

import os
import random
import sys
import time
from dataclasses import replace
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pokerbot.io.browser import Browser                                      # noqa: E402
from pokerbot.io.scraper import Scraper, reconstruct_preflop, to_game_state  # noqa: E402
from pokerbot.io.selectors import Selectors                    # noqa: E402
from pokerbot.model.state import Action, ActionType, Street     # noqa: E402
from pokerbot.opponents.classify import classify                # noqa: E402
from pokerbot.opponents.store import StatsStore                 # noqa: E402
from pokerbot.strategy.engine import decide, primary_villain_read  # noqa: E402


def _opt(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _reads(gs, store):
    if store is None:
        return None
    reads = {opp.seat_id: store.get(opp.name) for opp in gs.live_opponents if opp.name}
    return reads or None


def _synth_actions(gs, bb):
    """Live scraper can't read per-seat bets/log yet; if preflop and facing more than a limp,
    synthesize a raise so the engine treats it as facing a raise (not an open)."""
    if gs.street == Street.PREFLOP and gs.to_call > bb and gs.live_opponents:
        opp = gs.live_opponents[0]
        return (Action(opp.seat_id, ActionType.RAISE, gs.to_call + gs.hero.committed, Street.PREFLOP),)
    return ()


def main() -> None:
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = pos[0] if pos else input("PokerNow table URL: ").strip()
    sb, bb = Decimal(str(_opt("--sb", "0.5"))), Decimal(str(_opt("--bb", "1")))
    hero = _opt("--hero", None)

    db = os.path.join(os.path.dirname(__file__), "..", "data", "opponents.sqlite")
    store = StatsStore(db) if os.path.exists(db) else None

    browser = Browser(profile_dir=os.path.expanduser("~/.pokerbot-profile"))
    page = browser.open(url)
    input("\n>> Join/observe the table, then press Enter to start READ-ONLY watching...")
    scraper = Scraper(page, Selectors(), hero_name=hero)
    rng = random.Random()
    print(f"\nwatching (blinds {sb}/{bb}, profiles {'loaded' if store else 'none'}, "
          f"READ-ONLY, Ctrl-C to stop)...\n")

    last = None
    try:
        while True:
            if scraper.is_hero_turn():
                try:
                    raw = scraper.read_observation()
                    gs = reconstruct_preflop(to_game_state(raw, sb, bb), sb, bb)
                    actions = _synth_actions(gs, bb)
                    if actions:
                        gs = replace(gs, actions=actions)
                    sig = (tuple(map(str, gs.hero.cards)), tuple(map(str, gs.board)),
                           str(gs.to_call), gs.street.name)
                    if sig != last:
                        last = sig
                        reads = _reads(gs, store)
                        d = decide(gs, rng, iterations=3000, reads=reads)
                        villain = primary_villain_read(gs, reads)
                        vtag = f"  vs {classify(villain)}" if villain and villain.hands >= 15 else ""
                        hole = " ".join(map(str, gs.hero.cards)) or "??"
                        board = " ".join(map(str, gs.board)) or "-"
                        amt = f" {d.amount}" if d.action.name in ("BET", "RAISE") else ""
                        eq = f" eq={d.equity:.2f}" if d.equity is not None else ""
                        print(f"[{gs.street.name}] {hole} | board {board} | pos {gs.hero_position} "
                              f"| {gs.num_live_opponents} opp | pot {gs.pot} to-call {gs.to_call}{vtag}")
                        print(f"   => WOULD {d.action.name}{amt}{eq}   {d.rationale}\n")
                except Exception as e:  # noqa: BLE001 - keep watching through transient read errors
                    print("read error:", e)
                time.sleep(0.5)
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\nstopped.")
        browser.close()


if __name__ == "__main__":
    main()
