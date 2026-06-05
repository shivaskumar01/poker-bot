"""SQLite-backed persistence for PlayerStats so reads accumulate across sessions.

One row per player name, holding every counter. CHECK constraints keep counts non-negative
(defense-in-depth). Use ':memory:' for tests.
"""
from __future__ import annotations

import sqlite3

from .stats import PlayerStats, Stat

_STAT_FIELDS = ["vpip", "pfr", "threebet", "fold_to_3bet", "cbet_flop", "fold_to_cbet_flop", "wtsd"]
_SCALARS = ["hands", "agg_actions", "call_actions"]
_COUNTER_COLS = [f"{f}_{kind}" for f in _STAT_FIELDS for kind in ("made", "opp")]
_ALL_COLS = _SCALARS + _COUNTER_COLS


class StatsStore:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        cols = ",\n            ".join(
            f"{c} INTEGER NOT NULL DEFAULT 0 CHECK({c} >= 0)" for c in _ALL_COLS
        )
        self.conn.execute(
            f"CREATE TABLE IF NOT EXISTS player_stats (\n"
            f"            name TEXT PRIMARY KEY,\n            {cols}\n        )"
        )
        self.conn.commit()

    def get(self, name: str) -> PlayerStats:
        cur = self.conn.execute("SELECT * FROM player_stats WHERE name = ?", (name,))
        row = cur.fetchone()
        hu = name.endswith("#hu")                 # heads-up-only profile (looser baselines)
        if row is None:
            return PlayerStats(name=name, heads_up=hu)
        data = dict(zip((d[0] for d in cur.description), row))
        ps = PlayerStats(
            name=name, hands=data["hands"], heads_up=hu,
            agg_actions=data["agg_actions"], call_actions=data["call_actions"],
        )
        for f in _STAT_FIELDS:
            setattr(ps, f, Stat(made=data[f"{f}_made"], opp=data[f"{f}_opp"]))
        return ps

    def save(self, ps: PlayerStats) -> None:
        vals: dict[str, object] = {
            "name": ps.name, "hands": ps.hands,
            "agg_actions": ps.agg_actions, "call_actions": ps.call_actions,
        }
        for f in _STAT_FIELDS:
            s: Stat = getattr(ps, f)
            vals[f"{f}_made"] = s.made
            vals[f"{f}_opp"] = s.opp
        cols = list(vals.keys())
        placeholders = ", ".join("?" * len(cols))
        self.conn.execute(
            f"INSERT OR REPLACE INTO player_stats ({', '.join(cols)}) VALUES ({placeholders})",
            [vals[c] for c in cols],
        )
        self.conn.commit()

    def clear(self) -> None:
        """Wipe all profiles — used before a full rebuild so stale/renamed rows don't linger."""
        self.conn.execute("DELETE FROM player_stats")
        self.conn.commit()

    def all_players(self) -> list[PlayerStats]:
        names = [r[0] for r in self.conn.execute("SELECT name FROM player_stats").fetchall()]
        return [self.get(n) for n in names]

    def close(self) -> None:
        self.conn.close()
