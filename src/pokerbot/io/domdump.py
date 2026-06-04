"""Print + persist the live DOM (every frame, all inputs + attributes, all buttons).

Used to calibrate selectors against PokerNow's real markup. A backgrounded app block-buffers stdout,
so the dump is ALSO appended (with flush) to a file that can be read back directly:
  default ~/poker-bot/data/dom_dump.txt  (override with $POKERBOT_DUMP)
"""
from __future__ import annotations

import os
import time

_ATTRS = ("type", "name", "id", "placeholder", "value", "maxlength", "inputmode", "autocomplete",
          "aria-label", "class")
_DEFAULT_DUMP = os.path.expanduser("~/poker-bot/data/dom_dump.txt")


def scopes(page):
    """The page plus every iframe — modals sometimes render in a child frame."""
    try:
        frames = getattr(page, "frames", None)
        return list(frames) if frames else [page]
    except Exception:  # noqa: BLE001
        return [page]


def _render(page, tag: str) -> str:
    lines = [f"\n===== DOM [{tag}] {time.strftime('%Y-%m-%d %H:%M:%S')} ====="]
    for i, fr in enumerate(scopes(page)):
        url = getattr(fr, "url", "?")
        url = url() if callable(url) else url
        try:
            txt = (fr.inner_text("body") or "").strip().replace("\n", " ")[:400]
        except Exception:  # noqa: BLE001
            txt = "(no text)"
        lines.append(f"[frame {i}] {url}\n  text: {txt}")
        try:
            for el in (fr.query_selector_all("input, textarea, [contenteditable='true']") or []):
                attrs = {a: el.get_attribute(a) for a in _ATTRS}
                lines.append(f"  INPUT vis={el.is_visible()} {attrs}")
        except Exception:  # noqa: BLE001
            pass
        try:
            btns = [(el.inner_text() or "").strip()[:40]
                    for el in (fr.query_selector_all("button, [role='button'], a.button") or [])
                    if el.is_visible()]
            lines.append(f"  BUTTONS: {btns}")
        except Exception:  # noqa: BLE001
            pass
    lines.append("===== END DOM =====")
    return "\n".join(lines)


def dump_dom(page, tag: str, out=None) -> None:
    try:
        text = _render(page, tag)
    except Exception:  # noqa: BLE001
        return
    try:
        print(text, flush=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        path = os.environ.get("POKERBOT_DUMP", _DEFAULT_DUMP)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(text + "\n")
            f.flush()
    except Exception:  # noqa: BLE001
        pass
