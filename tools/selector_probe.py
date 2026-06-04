"""Live DOM calibration for PokerNow selectors. RUN THIS ON YOUR OWN OPEN TABLE.

    PYTHONPATH=src ./.venv/bin/python tools/selector_probe.py "https://www.pokernow.club/games/<id>"

Opens a real Chrome (persistent profile, so login sticks), waits for you to log in and join
/ observe the table, then reports: (1) how the current best-effort selectors do, and (2) a
DOM scan of buttons / card-like / player-like elements. Paste the JSON back and I'll fill
src/pokerbot/io/selectors.py with the verified selectors.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pokerbot.io.browser import Browser          # noqa: E402
from pokerbot.io.selectors import Selectors      # noqa: E402

SCAN_JS = r"""
() => {
  const t = e => (e.innerText || '').trim().slice(0, 50);
  const buttons = [...document.querySelectorAll('button')]
      .map(b => ({text: t(b), cls: b.className})).filter(b => b.text);
  const cards = [...document.querySelectorAll('*')]
      .filter(e => e.children.length === 0 && /[♠♥♦♣]/.test(e.textContent || ''))
      .slice(0, 14).map(e => ({text: t(e), cls: e.className, tag: e.tagName}));
  const players = [...document.querySelectorAll('[class*="player"]')]
      .slice(0, 14).map(e => ({cls: e.className, text: t(e)}));
  const pots = [...document.querySelectorAll('[class*="pot"]')]
      .slice(0, 8).map(e => ({cls: e.className, text: t(e)}));
  return {buttons, cards, players, pots};
}
"""


def report_current(page, sel: Selectors) -> None:
    for name, val in vars(sel).items():
        if not isinstance(val, str):
            continue
        try:
            els = page.query_selector_all(val)
            sample = (els[0].inner_text()[:30] if els else "").replace("\n", " ")
        except Exception as e:  # noqa: BLE001 - report, don't crash calibration
            els, sample = [], f"<err: {e}>"
        print(f"  {name:14s} {val[:36]:36s} -> {len(els):2d} match   {sample!r}")


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else input("PokerNow table URL: ").strip()
    browser = Browser(profile_dir=os.path.expanduser("~/.pokerbot-profile"), headless=False)
    page = browser.open(url)
    input("\n>> Log in and JOIN or OBSERVE the table, then press Enter here to scan...")

    print("\n=== current best-effort selectors (match counts) ===")
    report_current(page, Selectors())

    print("\n=== DOM scan ===")
    data = page.evaluate(SCAN_JS)
    for section in ("buttons", "cards", "players", "pots"):
        print(f"\n-- {section} --")
        for item in data.get(section, []):
            print("   ", item)

    out = os.path.join(os.path.dirname(__file__), "..", "data", "selector_probe_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"\nwrote {out}\nPaste that file's contents back and I'll finalize io/selectors.py.")
    input("press Enter to close the browser...")
    browser.close()


if __name__ == "__main__":
    main()
