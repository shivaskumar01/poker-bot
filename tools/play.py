"""Run the bot live on PokerNow. Reads config.yaml.

Defaults to OBSERVE (reads + narrates, never clicks). To let it actually act, set in config.yaml:
    mode: execute
    players_consent: true        # everyone at the table knows a bot is playing
and ideally a stop_loss_bb. Safe-stop any time by creating a file named STOP (touch STOP) in
this directory, or Ctrl-C.

    PYTHONPATH=src ./.venv/bin/python tools/play.py ["https://www.pokernow.com/games/<id>"]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pokerbot.io.browser import Browser              # noqa: E402
from pokerbot.io.executor import Executor            # noqa: E402
from pokerbot.io.scraper import Scraper              # noqa: E402
from pokerbot.io.selectors import Selectors          # noqa: E402
from pokerbot.opponents.store import StatsStore      # noqa: E402
from pokerbot.runtime.config import load_config      # noqa: E402
from pokerbot.runtime.orchestrator import LiveBot    # noqa: E402
from pokerbot.runtime.safety import Limits, SessionGuard  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def main() -> None:
    cfg = load_config(os.path.join(ROOT, "config.yaml"))
    url = sys.argv[1] if len(sys.argv) > 1 else (cfg.table_url or input("PokerNow table URL: ").strip())

    if cfg.mode == "execute" and not cfg.players_consent:
        print("!! mode=execute but players_consent=false -> refusing to click; running OBSERVE-only.\n")
    if cfg.mode == "execute" and cfg.players_consent:
        print("!! EXECUTE mode: the bot WILL click actions. Everyone must consent. "
              "Create a 'STOP' file to halt.\n")

    browser = Browser(profile_dir=os.path.expanduser("~/.pokerbot-profile"))
    page = browser.open(url)
    input(">> Log in + sit at the table, then press Enter to start...")

    db = os.path.join(ROOT, cfg.db_path)
    store = StatsStore(db) if os.path.exists(db) else None
    selectors = Selectors()
    scraper = Scraper(page, selectors, hero_name=cfg.hero_name)
    executor = Executor(page, selectors, mode=cfg.mode, players_consent=cfg.players_consent)
    guard = SessionGuard(Limits(cfg.stop_loss_bb, cfg.stop_win_bb, cfg.max_hands),
                         cfg.big_blind, kill_file=os.path.join(ROOT, cfg.kill_file))
    os.makedirs(os.path.dirname(os.path.join(ROOT, cfg.hand_log_path)), exist_ok=True)
    logfile = open(os.path.join(ROOT, cfg.hand_log_path), "a", encoding="utf-8")

    bot = LiveBot(scraper, executor, store, cfg, guard, logfile=logfile)
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\nstopped (Ctrl-C).")
    finally:
        logfile.close()
        browser.close()


if __name__ == "__main__":
    main()
