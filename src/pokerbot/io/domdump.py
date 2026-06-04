"""Print the live DOM (every frame, all inputs + their attributes, all buttons).

Used to calibrate selectors against PokerNow's real markup: when a flow can't find what it needs,
it dumps the actual DOM so the exact selector can be read off the app's console output.
"""
from __future__ import annotations

import time

_ATTRS = ("type", "name", "id", "placeholder", "value", "maxlength", "inputmode", "autocomplete",
          "aria-label", "class")


def scopes(page):
    """The page plus every iframe — modals sometimes render in a child frame."""
    try:
        frames = getattr(page, "frames", None)
        return list(frames) if frames else [page]
    except Exception:  # noqa: BLE001
        return [page]


def dump_dom(page, tag: str, out=print) -> None:
    try:
        lines = [f"\n===== DOM [{tag}] {time.strftime('%H:%M:%S')} ====="]
        for i, fr in enumerate(scopes(page)):
            url = getattr(fr, "url", "?")
            url = url() if callable(url) else url
            try:
                txt = (fr.inner_text("body") or "").strip().replace("\n", " ")[:300]
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
        lines.append("===== END DOM =====\n")
        out("\n".join(lines))
    except Exception:  # noqa: BLE001
        pass
