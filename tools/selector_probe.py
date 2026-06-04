"""Live DOM calibration for PokerNow selectors. RUN THIS ON YOUR OWN OPEN TABLE.

    PYTHONPATH=src ./.venv/bin/python tools/selector_probe.py "https://www.pokernow.com/games/<id>"

For the dynamic elements (cards, bets, board, dealer button, action buttons, raise slider)
to be visible, run it DURING A LIVE HAND and press Enter when it is YOUR TURN to act. It
opens a real Chrome (persistent profile, so login sticks), auto-opens the LOG panel, then
dumps a DOM scan to data/selector_probe_report.json. Paste that back and I'll finalize
src/pokerbot/io/selectors.py.
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
  const t = e => (e.innerText || '').trim().slice(0, 40);
  const snip = e => (e.outerHTML || '').replace(/\s+/g, ' ').slice(0, 140);
  const pick = (sel, n = 16) => [...document.querySelectorAll(sel)].slice(0, n);
  return {
    action_buttons: pick('.game-decisions-ctn button').map(b => ({text: t(b), cls: b.className})),
    cards: pick('[class*="card"]').map(e => ({cls: e.className, text: t(e), html: snip(e)})),
    seated: pick('.table-player:not(.table-player-seat)').map(e => ({cls: e.className, text: t(e)})),
    bets: pick('[class*="bet"]').map(e => ({cls: e.className, text: t(e)})),
    dealers: pick('[class*="dealer"]').map(e => ({cls: e.className, text: t(e), html: snip(e)})),
    inputs: pick('input, [class*="raise"], [class*="slider"]')
        .map(e => ({tag: e.tagName, cls: e.className, type: e.type || ''})),
    log: pick('[class*="log"] [class*="message"], .log-3 .message', 12)
        .map(e => ({cls: e.className, text: t(e)})),
  };
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
        print(f"  {name:14s} {val[:42]:42s} -> {len(els):2d} match   {sample!r}")


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else input("PokerNow table URL: ").strip()
    browser = Browser(profile_dir=os.path.expanduser("~/.pokerbot-profile"), headless=False)
    page = browser.open(url)
    input("\n>> Log in, JOIN the table, and PLAY a hand. When it is YOUR TURN to act\n"
          "   (Fold/Call/Raise buttons + your cards + bets visible), press Enter to scan...")

    try:                       # auto-open the LOG panel so we can see its structure
        page.click(".show-log-button", timeout=2500)
        page.wait_for_timeout(800)
    except Exception:
        pass

    print("\n=== current best-effort selectors (match counts) ===")
    report_current(page, Selectors())

    print("\n=== DOM scan ===")
    data = page.evaluate(SCAN_JS)
    for section in ("action_buttons", "cards", "bets", "dealers", "inputs", "seated", "log"):
        print(f"\n-- {section} ({len(data.get(section, []))}) --")
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
