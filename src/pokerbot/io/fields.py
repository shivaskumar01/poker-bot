"""Typing into PokerNow's React-controlled inputs (shared by the executor and the seater).

A plain `fill()` sets the DOM value without firing React's onChange, so the app never sees it
("must be a value between 1 and 1.000.000"). Real keystrokes (`press_sequentially`/`type`) do;
`fill` is the last resort. Clears any prefill first. None-safe: a missing element returns False.
"""
from __future__ import annotations


def type_into(el, text: str) -> bool:
    if el is None:
        return False
    try:
        el.click()
    except Exception:  # noqa: BLE001
        pass
    try:
        el.fill("")
    except Exception:  # noqa: BLE001
        pass
    for meth in ("press_sequentially", "type"):
        fn = getattr(el, meth, None)
        if fn is None:
            continue
        try:
            fn(text, delay=40)
            return True
        except TypeError:
            try:
                fn(text)
                return True
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
    try:
        el.fill(text)
        return True
    except Exception:  # noqa: BLE001
        return False
