"""Playwright browser session for PokerNow.

Uses a *persistent* context (a real on-disk profile) so a one-time manual login sticks
across runs — we never handle credentials. Headful by default so you can log in and watch.
"""
from __future__ import annotations

from playwright.sync_api import Page, sync_playwright


class Browser:
    def __init__(self, profile_dir: str = "playwright-profile", headless: bool = False) -> None:
        self.profile_dir = profile_dir
        self.headless = headless
        self._pw = None
        self.context = None
        self.page: Page | None = None

    def open(self, url: str | None = None) -> Page:
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            self.profile_dir, headless=self.headless, viewport={"width": 1440, "height": 900}
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        if url:
            self.page.goto(url)
        return self.page

    def close(self) -> None:
        if self.context:
            self.context.close()
        if self._pw:
            self._pw.stop()

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
