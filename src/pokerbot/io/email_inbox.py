"""A real, disposable email inbox for PokerNow's login verification code.

PokerNow gates its video/voice chat behind an email login: you enter an address, it emails a
6-digit code, you type the code back in. A made-up string won't receive the code, so we create a
genuine throwaway inbox via the free mail.tm REST API (a valid, deliverable address we can poll),
read PokerNow's code out of it, and hand it back to the page. No personal credentials involved.

If mail.tm is unreachable or PokerNow rejects disposable domains, `create()` raises and the caller
falls back to manual entry. The single HTTP helper `_req` is module-level so tests can stub it.
"""
from __future__ import annotations

import json
import random
import re
import string
import time
import urllib.error
import urllib.request

API = "https://api.mail.tm"
_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _req(method: str, path: str, token: str | None = None, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(API + path, data=body, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else {}


def _members(resp):
    """mail.tm collections come back either as a bare JSON array or a Hydra {'hydra:member': [...]}."""
    if isinstance(resp, list):
        return resp
    return resp.get("hydra:member", []) if isinstance(resp, dict) else []


class TempInbox:
    def __init__(self, address: str, token: str) -> None:
        self.address = address
        self.token = token

    @classmethod
    def create(cls, rng: random.Random | None = None) -> "TempInbox":
        rng = rng or random.Random()
        domains = _members(_req("GET", "/domains"))
        domain = next((d["domain"] for d in domains if d.get("isActive", True)), None)
        if not domain:
            raise RuntimeError("no active mail.tm domain available")
        local = "".join(rng.choice(string.ascii_lowercase) for _ in range(10)) + str(rng.randint(100, 999))
        address = f"{local}@{domain}"
        password = "Pb!" + "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(12))
        _req("POST", "/accounts", data={"address": address, "password": password})
        token = _req("POST", "/token", data={"address": address, "password": password}).get("token")
        if not token:
            raise RuntimeError("mail.tm token request failed")
        return cls(address, token)

    def _scan_for_code(self, senders) -> str | None:
        """Newest-first scan of the inbox; returns the first 6-digit code (preferring PokerNow)."""
        msgs = _members(_req("GET", "/messages", token=self.token))

        def matches(m):
            frm = ((m.get("from") or {}).get("address") or "").lower()
            subj = (m.get("subject") or "").lower()
            return any(s in frm or s in subj for s in senders) if senders else True

        for m in sorted(msgs, key=matches, reverse=True):     # PokerNow messages first
            full = _req("GET", f"/messages/{m['id']}", token=self.token)
            html = full.get("html") or []
            blob = " ".join([m.get("subject", ""), m.get("intro", ""), full.get("text", ""),
                             " ".join(html) if isinstance(html, list) else str(html)])
            hit = _CODE_RE.search(blob)
            if hit:
                return hit.group(1)
        return None

    def wait_for_code(self, *, timeout: float = 120.0, sleep=time.sleep, should_stop=lambda: False,
                      senders=("pokernow",), log=lambda m: None) -> str | None:
        end = time.time() + timeout
        while time.time() < end and not should_stop():
            try:
                code = self._scan_for_code(senders)
                if code:
                    return code
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                log(f"inbox poll error: {e}")
            sleep(4.0)
        return None
