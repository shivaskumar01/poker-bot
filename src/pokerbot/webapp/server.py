"""Local Flask control panel for the bot.

Serves a single page that polls /api/state and shows the live hand + decision, opponent
profiles, and session stats. Start/Stop run the bot in a background thread (the bot drives
its own Chrome via Playwright, exactly like tools/play.py). Lightweight: polling, no sockets.
"""
from __future__ import annotations

import glob
import os
import random
import threading

from flask import Flask, jsonify, request, send_from_directory

from ..io.browser import Browser
from ..io.executor import Executor
from ..io.log_parser import parse_file
from ..io.scraper import Scraper
from ..io.seater import Seater
from ..io.selectors import Selectors
from ..opponents.classify import classify
from ..opponents.store import StatsStore
from ..opponents.tracking import accumulate, merge_aliases
from ..runtime.config import load_config
from ..runtime.orchestrator import LiveBot
from ..runtime.safety import Limits, SessionGuard
from ..strategy.engine import primary_villain_read
from ..strategy.timing import tempo_label

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))   # repo root (holds config.yaml, data/)
LEARNING_LOGS = os.path.expanduser("~/Desktop/Poker learning logs")


def _pct(stat) -> str:
    r = stat.raw
    return f"{r * 100:.0f}%" if r is not None else "—"


class BotController:
    """Owns the bot thread + a thread-safe snapshot of the live state for the UI to poll."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop_event: threading.Event | None = None
        self.browser: Browser | None = None
        self.guard: SessionGuard | None = None
        self.bot = None
        self.state = self._idle()

    def _idle(self) -> dict:
        return {"status": "idle", "mode": self.cfg.mode, "hand": None, "decision": None,
                "session": {"hands": 0, "net_bb": 0.0}, "log": [], "error": None,
                "blinds": {"sb": str(self.cfg.small_blind), "bb": str(self.cfg.big_blind)},
                "stack": None, "buy_in": str(self.cfg.buy_in), "needs_rebuy": False}

    def _set(self, **kw) -> None:
        with self.lock:
            self.state.update(kw)

    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def snapshot(self) -> dict:
        with self.lock:
            s = dict(self.state)
        s["running"] = self.running()
        return s

    def start(self, url: str, mode: str, consent: bool) -> bool:
        if self.running():
            return False
        self.cfg.mode = mode
        self.cfg.players_consent = consent
        self.cfg.table_url = url
        self.stop_event = threading.Event()
        with self.lock:
            self.state = self._idle()
            self.state.update(status="launching browser…", mode=mode)
        self.thread = threading.Thread(target=self._run, args=(url, mode, consent), daemon=True)
        self.thread.start()
        return True

    def stop(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        self._set(status="stopping…")

    def request_rebuy(self) -> bool:
        """UI confirmed a second buy-in — tell the bot thread to re-anchor + resume."""
        if self.bot is not None:
            self.bot.request_rebuy()
            return True
        return False

    def _on_status(self, d: dict) -> None:
        with self.lock:
            self.state["blinds"] = {"sb": d["small_blind"], "bb": d["big_blind"]}
            self.state["stack"] = d["stack"]
            self.state["buy_in"] = d["buy_in"]
            self.state["needs_rebuy"] = d["needs_rebuy"]
            self.state["session"] = {"hands": d["hands"], "net_bb": d["net_bb"]}
            if d["needs_rebuy"]:
                self.state["status"] = "bot busted — confirm a re-buy to keep playing"

    def _on_decision(self, gs, d, reads, think=None) -> None:
        villain = primary_villain_read(gs, reads)
        hole = [str(c) for c in gs.hero.cards]
        board = [str(c) for c in gs.board]
        hand = {"street": gs.street.name, "hole": hole, "board": board,
                "position": gs.hero_position, "pot": str(gs.pot), "to_call": str(gs.to_call),
                "opponents": gs.num_live_opponents,
                "villain": classify(villain) if villain and villain.hands >= 15 else None}
        amt = f" {d.amount}" if d.action.name in ("BET", "RAISE") else ""
        tempo = tempo_label(think, self.cfg.max_think) if think else ""
        line = (f"[{gs.street.name}] {' '.join(hole)} | {' '.join(board) or '-'} -> "
                f"{d.action.name}{amt}" + (f" ·{tempo}" if tempo else "") + f" ({d.rationale})")
        with self.lock:
            self.state["hand"] = hand
            self.state["decision"] = {"action": d.action.name, "amount": str(d.amount),
                                      "equity": d.equity, "rationale": d.rationale,
                                      "think": think, "tempo": tempo}
            self.state["status"] = "running"
            self.state["session"] = {"hands": self.guard.hands, "net_bb": round(self.guard.net_bb, 1)}
            self.state["log"] = ([line] + self.state.get("log", []))[:25]

    def _run(self, url: str, mode: str, consent: bool) -> None:
        cfg = self.cfg
        try:
            if not (url or "").strip():
                self._set(status="enter your PokerNow table URL, then Start", error="no table URL")
                return
            self.browser = Browser(profile_dir=os.path.expanduser("~/.pokerbot-profile"))
            self._set(status="launching browser…")
            page = self.browser.open(url)
            sel = Selectors()
            if cfg.hero_name and cfg.buy_in > 0:        # auto-seat: random open seat + buy-in
                self._set(status=f"taking an open seat as “{cfg.hero_name}” "
                                 f"(buy-in {cfg.buy_in})…")
                seater = Seater(page, sel, cfg.hero_name, cfg.buy_in, random.Random(),
                                log=lambda m: self._set(status=m),
                                should_stop=lambda: bool(self.stop_event and self.stop_event.is_set()))
                ok = seater.take_seat()
                self._set(status="seated — watching for your turn" if ok else
                          "couldn't auto-seat — sit manually. " + (seater.last_diag or ""))
            else:
                self._set(status="browser open — sit at the table; the bot acts on your turn "
                                 "(tip: set your name + buy-in to auto-seat next time)")
            db = os.path.join(ROOT, cfg.db_path)
            store = StatsStore(db) if os.path.exists(db) else None
            scraper = Scraper(page, sel, hero_name=cfg.hero_name)
            executor = Executor(page, sel, mode=mode, players_consent=consent)
            self.guard = SessionGuard(Limits(cfg.stop_loss_bb, cfg.stop_win_bb, cfg.max_hands),
                                      cfg.big_blind, kill_file=os.path.join(ROOT, cfg.kill_file),
                                      think=(cfg.min_think, cfg.max_think))
            bot = LiveBot(scraper, executor, store, cfg, self.guard,
                          on_decision=self._on_decision, on_status=self._on_status,
                          stop_event=self.stop_event)
            self.bot = bot
            bot.run()
            self._set(status="stopped")
        except Exception as e:  # noqa: BLE001 - surface errors to the UI
            self._set(status=f"error: {e}", error=str(e))
        finally:
            try:
                if self.browser:
                    self.browser.close()
            except Exception:  # noqa: BLE001
                pass
            self.browser = None
            self.bot = None


def create_app():
    cfg = load_config(os.path.join(ROOT, "config.yaml"))
    ctrl = BotController(cfg)
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(HERE, "index.html")

    @app.get("/api/state")
    def state():
        return jsonify(ctrl.snapshot())

    @app.get("/api/config")
    def get_config():
        return jsonify({"url": cfg.table_url, "sb": str(cfg.small_blind), "bb": str(cfg.big_blind),
                        "hero": cfg.hero_name or "", "mode": cfg.mode, "buy_in": str(cfg.buy_in),
                        "consent": cfg.players_consent, "stop_loss_bb": cfg.stop_loss_bb})

    @app.post("/api/start")
    def start():
        d = request.get_json(force=True) or {}
        cfg.small_blind = type(cfg.small_blind)(str(d.get("sb", cfg.small_blind)))
        cfg.big_blind = type(cfg.big_blind)(str(d.get("bb", cfg.big_blind)))
        cfg.buy_in = type(cfg.buy_in)(str(d.get("buy_in") or "0"))
        cfg.hero_name = (d.get("hero") or "").strip() or None
        ok = ctrl.start(d.get("url", "").strip(), d.get("mode", "observe"), bool(d.get("consent")))
        return jsonify({"ok": ok, "running": ctrl.running()})

    @app.post("/api/stop")
    def stop():
        ctrl.stop()
        return jsonify({"ok": True})

    @app.post("/api/rebuy")
    def rebuy():
        return jsonify({"ok": ctrl.request_rebuy()})

    @app.get("/api/profiles")
    def profiles():
        db = os.path.join(ROOT, cfg.db_path)
        out = []
        if os.path.exists(db):
            store = StatsStore(db)
            for ps in sorted(store.all_players(), key=lambda p: p.hands, reverse=True):
                out.append({"name": ps.name, "hands": ps.hands, "vpip": _pct(ps.vpip),
                            "pfr": _pct(ps.pfr), "threebet": _pct(ps.threebet),
                            "af": round(ps.af, 1), "fold_cbet": _pct(ps.fold_to_cbet_flop),
                            "wtsd": _pct(ps.wtsd), "type": classify(ps)})
            store.close()
        return jsonify(out)

    @app.post("/api/analyze")
    def analyze():
        files = glob.glob(os.path.join(LEARNING_LOGS, "*.csv"))
        if not files:
            return jsonify({"ok": False, "error": f"no logs in {LEARNING_LOGS}"})
        stats: dict = {}
        hands = 0
        for f in files:
            parsed = parse_file(f)
            hands += len(parsed)
            for h in parsed:
                accumulate(stats, h)
        stats = merge_aliases(stats)      # one profile per person (nicknames/ids/caps collapsed)
        db = os.path.join(ROOT, cfg.db_path)
        os.makedirs(os.path.dirname(db), exist_ok=True)
        store = StatsStore(db)
        store.clear()                     # full rebuild — drop stale/renamed rows first
        for ps in stats.values():
            store.save(ps)
        store.close()
        return jsonify({"ok": True, "players": len(stats), "hands": hands})

    return app, ctrl
