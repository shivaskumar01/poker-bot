"""Load config.yaml into a typed Config (money as Decimal)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import yaml


@dataclass
class Config:
    mode: str                  # observe | execute
    players_consent: bool
    table_url: str
    small_blind: Decimal
    big_blind: Decimal
    ante: Decimal
    hero_name: str | None      # None -> identify hero by the .you-player class
    stop_loss_bb: float
    stop_win_bb: float
    max_hands: int
    mc_iterations: int
    min_think: float
    max_think: float
    db_path: str
    hand_log_path: str
    kill_file: str


def load_config(path: str = "config.yaml") -> Config:
    with open(path) as fh:
        d = yaml.safe_load(fh) or {}
    stakes = d.get("stakes", {})
    limits = d.get("limits", {})
    engine = d.get("engine", {})
    timing = d.get("timing", {})
    table = d.get("table", {})
    return Config(
        mode=d.get("mode", "observe"),
        players_consent=bool(d.get("players_consent", False)),
        table_url=table.get("url", ""),
        small_blind=Decimal(str(stakes.get("small_blind", "0.50"))),
        big_blind=Decimal(str(stakes.get("big_blind", "1.00"))),
        ante=Decimal(str(stakes.get("ante", "0"))),
        hero_name=d.get("hero_name") or None,
        stop_loss_bb=float(limits.get("stop_loss_bb", 200)),
        stop_win_bb=float(limits.get("stop_win_bb", 400)),
        max_hands=int(limits.get("max_hands", 500)),
        mc_iterations=int(engine.get("mc_iterations", 1500)),
        min_think=float(timing.get("min_think_seconds", 1.5)),
        max_think=float(timing.get("max_think_seconds", 6.0)),
        db_path=d.get("opponents", {}).get("db_path", "data/opponents.sqlite"),
        hand_log_path=d.get("logging", {}).get("hand_log_path", "data/hands.jsonl"),
        kill_file=d.get("kill_file", "STOP"),
    )
