"""Table-nickname -> canonical player name.

A friend can sit under a different display name (or a new PokerNow account id) — e.g. bizz played
as 'Hungry horse'. Mapping nicknames to one canonical name keeps that person's HUD stats unified
when learning from logs AND lets the live bot apply the right read when it sees the nickname.

Add new nicknames here (lowercase key -> canonical name) as they come up.
"""
from __future__ import annotations

ALIASES = {
    "hungry horse": "bizz",
    "shivas": "shivas",          # collapse capitalization variants (Shivas/SHIVAS -> shivas)
}


def canonical(name: str | None) -> str:
    """Resolve a display name/nickname to its canonical player name (case-insensitive)."""
    if not name:
        return name or ""
    return ALIASES.get(name.strip().lower(), name.strip())
