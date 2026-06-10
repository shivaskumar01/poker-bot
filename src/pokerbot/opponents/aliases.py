"""Table-nickname -> canonical player name.

A friend can sit under a different display name (or a new PokerNow account id) — e.g. bizz played
as 'Hungry horse'. Mapping nicknames to one canonical name keeps that person's HUD stats unified
when learning from logs AND lets the live bot apply the right read when it sees the nickname.

ALL names canonicalize to lowercase (store keys are exact-match, so 'Vik' must hit the same
profile as 'vik' — re-capitalizing a name must never silently produce a blank read).

Add new nicknames here (lowercase key -> lowercase canonical name) as they come up.
"""
from __future__ import annotations

ALIASES = {
    "hungry horse": "bizz",
    "vani shah": "vik",
}


def canonical(name: str | None) -> str:
    """Resolve a display name/nickname to its canonical player name (lowercased, trimmed)."""
    if not name:
        return ""
    key = name.strip().lower()
    return ALIASES.get(key, key)
