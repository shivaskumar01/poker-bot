"""Playwright browser session for PokerNow.

Uses a *persistent* context (a real on-disk profile) so a one-time manual login sticks
across runs, we never handle credentials. Headful by default so you can log in and watch.
"""
from __future__ import annotations

import os
import subprocess
import time

from playwright.sync_api import Page, sync_playwright


class Browser:
    def __init__(self, profile_dir: str = "playwright-profile", headless: bool = False) -> None:
        self.profile_dir = os.path.abspath(os.path.expanduser(profile_dir))
        self.headless = headless
        self._pw = None
        self.context = None
        self.page: Page | None = None

    def _free_profile(self) -> None:
        """A persistent profile can be driven by only ONE Chromium at a time. If a previous run's
        Chrome is still alive (or crashed) it holds the profile's Singleton lock and the next launch
        fails with 'Opening in existing browser session' (the new window just shows about:blank).
        Kill any Chrome using THIS exact profile, then clear the stale lock files."""
        pat = f"--user-data-dir={self.profile_dir}"
        for sig in ("-TERM", "-KILL"):
            try:
                subprocess.run(["pkill", sig, "-f", pat], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:  # noqa: BLE001 - cleanup is best-effort
                pass
            time.sleep(0.5)
        for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                os.unlink(os.path.join(self.profile_dir, lock))
            except OSError:
                pass

    def _launch(self):
        return self._pw.chromium.launch_persistent_context(
            self.profile_dir, headless=self.headless, viewport={"width": 1440, "height": 900},
        )

    def open(self, url: str | None = None) -> Page:
        self._pw = sync_playwright().start()
        try:
            self.context = self._launch()
        except Exception as e:  # noqa: BLE001 - one retry after freeing a stale profile lock
            if "existing browser session" in str(e) or "ProcessSingleton" in str(e):
                self._free_profile()
                self.context = self._launch()
            else:
                raise
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        if url:
            self.page.goto(url, wait_until="domcontentloaded")
        return self.page

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
        except Exception:  # noqa: BLE001 - closing must never raise
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self.context = None
        self._pw = None
        self.page = None

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
