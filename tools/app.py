"""Launch the local web control panel for the bot.

    PYTHONPATH=src ./.venv/bin/python tools/app.py
    -> opens http://127.0.0.1:8765 in your browser.

The page lets you set the table/blinds/mode, Start/Stop the bot, watch the live hand +
decision, see opponent profiles, and re-learn from your logs. The bot still drives its own
Chrome (Playwright) for PokerNow; this is just the control + monitor surface.
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pokerbot.webapp.server import create_app   # noqa: E402


def main() -> None:
    app, _ctrl = create_app()
    port = int(os.environ.get("PORT", "8765"))
    url = f"http://127.0.0.1:{port}"
    print(f"\n  ♠ Poker Bot control panel  ->  {url}\n  (Ctrl-C to quit)\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
