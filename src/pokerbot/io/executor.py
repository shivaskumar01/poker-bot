"""Translate a Decision into PokerNow clicks, behind a hard consent gate.

`execute` is a no-op (returns False, never touches the page) unless mode == 'execute' AND
players_consent is True. Buttons are located by class (`button.fold/.check/.call/.raise`).

A RAISE/BET is THREE steps on PokerNow: click RAISE to open the bet panel, type the amount, then
click the confirm button (which then reads 'RAISE TO X' / 'BET X' / 'ALL IN'). Doing only the first
step leaves the panel open and the bot gets auto-folded, so this does all three and verifies.
"""
from __future__ import annotations

import re
import time
from decimal import Decimal
from pathlib import Path

from ..model.state import ActionType
from ..strategy.decision import Decision
from .domdump import dump_dom
from .fields import type_into

_CONFIRM_RE = re.compile(r"raise to|bet to|^\s*bet\s+[\d.,]|confirm|^\s*go\s*$", re.I)
# the bet panel's own controls, NEVER click these as a "confirm" (ALL IN would re-size the bet!)
_PANEL_CTRL_RE = re.compile(r"pot|all[\s-]?in|min\s*raise|^\s*back\s*$|^\s*[-+]\s*$", re.I)
_BETLOG = Path("data/bet_log.txt")          # paper trail of decided-vs-actually-did (gitignored)


class Executor:
    def __init__(self, page, selectors, *, mode: str = "observe",
                 players_consent: bool = False) -> None:
        self.page = page
        self.sel = selectors
        self.mode = mode
        self.players_consent = players_consent
        self._raise_dumped = False
        self._set_dumped = False
        self._fallback_dumps = 0     # bounded DOM dumps on the disconnect (couldn't-size) path
        self._last_set: float | None = None   # the box value we actually verified+confirmed

    @property
    def can_act(self) -> bool:
        return self.mode == "execute" and self.players_consent

    def _is_hero_turn(self) -> bool:
        """The hero is the CURRENT ACTOR, and the on-screen controls are the REAL action
        controls, not PokerNow's PRE-ACTION toggles.

        `.decision-current` alone LIES for a window right after the hero acts (it lingers on the
        hero seat until the server confirms, proven by a live DOM dump) and around a pause. In
        that window PokerNow shows amount-less RAISE/CHECK/FOLD toggles that QUEUE an action for
        the next turn; clicking the queued RAISE fires later at the REMEMBERED amount (the last
        street's bet), the live 'turn lead = flop lead' bug. Real-turn markers (any one):
          * the bet panel is open (it can only exist on a real turn), or
          * an action-area button carries an AMOUNT: 'CALL 25.00' / the 'BET 2.00' min-shortcut /
            'ACTIVATE EXTRA TIME (10S)', pre-action toggles are always amount-less, or
          * the action area shows the YOUR TURN tag."""
        try:
            if self.page.query_selector(f".you-player.{self.sel.current_actor_class}") is None:
                return False
            if self._panel_open():
                return True
            for b in (self.page.query_selector_all(f"{self.sel.action_area} button") or []):
                try:
                    if b.is_visible() and re.search(r"\d", b.inner_text() or ""):
                        return True
                except Exception:  # noqa: BLE001
                    continue
            area = self.page.query_selector(self.sel.action_area)
            return bool(area and "your turn" in (area.inner_text() or "").lower())
        except Exception:  # noqa: BLE001
            return False

    def execute(self, decision: Decision) -> bool:
        """Perform the action. Returns False (touching nothing) if unauthorized, not actually the
        hero's turn, or the control isn't found. Logs decided-vs-actually-did every time so any
        dashboard/execution disconnect leaves a ground-truth trail in data/bet_log.txt."""
        if not self.can_act:
            return False
        if not self._is_hero_turn():
            # CRITICAL: only ever click while it's genuinely our turn. If the turn already passed
            # (slow think / a long bet sequence), the on-screen controls are PRE-ACTION ('check/fold
            # ahead') that PokerNow QUEUES for next turn -> the bot would act one street behind.
            return False
        ok, did = self._dispatch(decision)
        self._betlog(decision, did, ok)
        return ok

    def _dispatch(self, decision: Decision) -> tuple[bool, str]:
        """Click the action and report (success, what-actually-happened) for the log."""
        a = decision.action
        if a == ActionType.FOLD:
            return self._click(self.sel.btn_fold), "fold"
        if a == ActionType.CHECK:
            # NEVER fall back to .call here: when a check is available, PokerNow's .call button is
            # the 'BET <min>' shortcut, so clicking it would MIN-BET instead of checking.
            return self._click(self.sel.btn_check), "check"
        if a == ActionType.CALL:
            return self._click(self.sel.btn_call), "call"
        if a in (ActionType.BET, ActionType.RAISE):
            self._last_set = None
            res = self._raise_to(decision.amount)
            if res == "confirmed":
                got = self._last_set if self._last_set is not None else float(decision.amount)
                return True, f"{a.name.lower()}→{got:.2f}"
            if res == "abort":
                # the controls weren't live (turn flipped / pre-action toggles / pause), touch
                # NOTHING and let the orchestrator retry on the real turn. Falling back here would
                # click a pre-action toggle and queue a stale action.
                return False, "controls not live (turn passed / pre-action), no click"
            # res == "fallback": the panel was real but the amount couldn't be sized -> NEVER
            # confirm a min bet. A BET is checkable, so CHECK; a RAISE faces a bet (incl. an
            # all-in jam), so CALL. Snapshot the DOM to diagnose the disconnect.
            if self._fallback_dumps < 10:
                self._fallback_dumps += 1
                dump_dom(self.page, f"FALLBACK target={float(decision.amount):.2f} "
                                    f"box={self._amount_str()!r}")
            self._close_panel()        # the panel hides check/call, close it or the clicks miss
            if not self._is_hero_turn():
                return False, "turn passed before the fallback, no click"
            if a == ActionType.BET:
                return self._click(self.sel.btn_check), "FALLBACK-check (couldn't size bet)"
            return self._click(self.sel.btn_call), "FALLBACK-call (couldn't size raise)"
        return False, "noop"

    def _betlog(self, decision: Decision, did: str, ok: bool) -> None:
        """Append one line: what the dashboard decided vs. what the executor actually did."""
        try:
            want = f"{decision.action.name} {float(decision.amount):.2f}"
            disc = "" if ok and ("FALLBACK" not in did) else "   <-- DISCONNECT"
            _BETLOG.parent.mkdir(parents=True, exist_ok=True)
            with _BETLOG.open("a") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')}  decided {want:<14} did {did:<24} "
                         f"ok={ok}{disc}\n")
        except Exception:  # noqa: BLE001 - logging must never break execution
            pass

    # --- raise/bet: open panel -> set amount (VERIFIED) -> confirm ----------
    def _raise_to(self, amount: Decimal) -> str:
        """Confirm ONLY a verified amount. Returns:
          'confirmed', the verified amount was submitted;
          'abort', the controls aren't live (turn flipped / RAISE was a pre-action toggle):
                        NOTHING may be clicked afterwards, the toggle queues an action that fires
                        NEXT turn at PokerNow's remembered amount (the 'turn lead = flop lead' bug);
          'fallback', a real panel existed but no sane amount could be set (the caller takes a
                        free check / a call), it NEVER confirms the panel's default min bet."""
        for _ in range(3):
            if not self._is_hero_turn():               # the turn evaporated mid-flow (pause/flip)
                return "abort"
            if not self._panel_open():                 # open the bet panel (skip if a retry left it open)
                if not self._click(self.sel.btn_raise):
                    return "fallback"                  # no raise control at all (e.g. facing a jam) -> call
                self._await_panel()                    # WAIT for the amount field to actually render
                if not self._panel_open():
                    # the click hit something that ISN'T the real raise button (a pre-action
                    # toggle): click it again to UN-QUEUE the stale raise, then walk away.
                    self._click(self.sel.btn_raise)
                    return "abort"
            if not self._raise_dumped:
                self._raise_dumped = True
                dump_dom(self.page, "after-raise-click")
            if self._set_amount(amount) and self._click_confirm():   # set+VERIFY, then confirm
                return "confirmed"
            self._wait(160)                            # settle, then retry the open/size
        return "fallback"

    def _await_panel(self) -> None:
        """Block until the bet panel's amount field is actually on screen, a fixed delay was
        sometimes too short, leaving the field unset so the default (a min bet) got confirmed."""
        try:
            self.page.wait_for_selector(self.sel.raise_amount, state="visible", timeout=1500)
        except Exception:  # noqa: BLE001
            self._wait(300)
        self._wait(100)

    def _click_label(self, pattern: str) -> bool:
        rx = re.compile(pattern, re.I)
        for b in (self.page.query_selector_all(f"{self.sel.action_area} button, button") or []):
            try:
                if b.is_visible() and rx.search((b.inner_text() or "").strip()):
                    b.click(timeout=1500)
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    _PRESETS = (("1/2-pot", r"1/2\s*pot"), ("3/4-pot", r"3/4\s*pot"),
                ("pot", r"^\s*pot\s*$"), ("all-in", r"all[\s-]?in"))

    def _preset_near(self, target: float) -> str:
        """When the exact amount won't type, fall back to the POT-relative preset CLOSEST to the
        target (¼/½/¾/pot/all-in), and only if it's within ~20% of target. Tries each, reads the
        amount it produces, then re-selects the closest. Never a wildly-off size; never a min bet."""
        produced = {}
        for label, rx in self._PRESETS:
            if self._click_label(rx):
                self._wait(70)
                got = self._amount_value()
                if got is not None:
                    produced[label] = (rx, got)
        if not produced:
            return "none"
        label, (rx, got) = min(produced.items(), key=lambda kv: abs(kv[1][1] - target))
        if abs(got - target) > 0.20 * target:          # nothing close enough -> let the caller check/call
            return "none"
        self._click_label(rx)                          # re-select the closest preset (last click left a different one)
        self._wait(70)
        now = self._amount_value()                     # VERIFY the re-select stuck: the last probe was
        if now is None or abs(now - target) > 0.20 * target:   # ALL IN, so an unverified miss would
            return "none"                              # confirm a jam. Never confirm what we can't read.
        return label

    def activate_extra_time(self) -> bool:
        """Click PokerNow's 'ACTIVATE EXTRA TIME' to buy clock on a big decision (no-op once used
        this turn / if absent). Lets the bot tank a big pot without getting auto-folded."""
        try:
            for b in (self.page.query_selector_all(f"{self.sel.action_area} button, button") or []):
                t = (b.inner_text() or "").upper()
                if "ACTIVATE" in t and "EXTRA TIME" in t and b.is_visible() and b.is_enabled():
                    b.click(timeout=1500)
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def _panel_open(self) -> bool:
        try:
            return bool(self.page.query_selector(self.sel.raise_confirm)
                        or self.page.query_selector(self.sel.raise_amount))
        except Exception:  # noqa: BLE001
            return False

    def _close_panel(self) -> None:
        """Close an open bet panel (click BACK). The panel REPLACES the check/call/fold buttons on
        screen, so a couldn't-size fallback MUST close it first or its check/call click hits nothing
        and the bot burns its clock retrying."""
        if not self._panel_open():
            return
        self._click_label(r"^\s*back\s*$")
        self._wait(120)

    def _click_confirm(self) -> bool:
        if self._click(self.sel.raise_confirm):        # <input type=submit value="Raise/Bet">
            return True
        try:    # the REAL confirm is an <input type=submit>, never a <button>, find it directly
            for el in (self.page.query_selector_all("input[type='submit']") or []):
                if el.is_visible():
                    el.click(timeout=2000)
                    return True
        except Exception:  # noqa: BLE001
            pass
        for sel in (f"{self.sel.action_area} button", ".action-buttons button"):  # other variants
            try:
                for b in (self.page.query_selector_all(sel) or []):
                    t = (b.inner_text() or "").strip()
                    # exclude the panel's own preset/stepper controls: clicking 'ALL IN' here would
                    # RE-SIZE the bet to a jam, not confirm it (a catastrophic mis-click)
                    if b.is_visible() and _CONFIRM_RE.search(t) and not _PANEL_CTRL_RE.search(t):
                        b.click(timeout=2000)
                        return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _click(self, selector: str) -> bool:
        """Robust click: a Locator (re-resolves on re-render) with a SHORT timeout so a momentarily
        un-clickable control never hangs 30s and gets the bot auto-folded; force-clicks through a
        transient overlay on the second try."""
        try:
            loc = self.page.locator(selector).first
        except Exception:  # noqa: BLE001
            return False
        for force in (False, True):
            try:
                loc.click(timeout=2000, force=force)
                return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _wait(self, ms: int) -> None:
        try:
            self.page.wait_for_timeout(ms)
        except Exception:  # noqa: BLE001
            pass

    _NATIVE_SET = ("(n,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')"
                   ".set;s.call(n,v);n.dispatchEvent(new Event('input',{bubbles:true}));"
                   "n.dispatchEvent(new Event('change',{bubbles:true}));}")

    def _set_amount(self, amount: Decimal) -> bool:
        """Set the bet amount and VERIFY the box reads it. Returns True ONLY if a sane amount is
        confirmed (an exact set, or a clean preset in the ballpark), so the caller will never
        confirm the panel's default min bet."""
        target = float(amount)
        cents = str(int((amount * 100).to_integral_value()))   # 100.00 -> '10000' (cents keypad)
        dec = f"{amount:.2f}"                                   # '100.00' (decimal form)
        # Slider FIRST, proven reliable on this table (sets the exact value for clean step amounts,
        # which the bot's BB-rounded sizes are). Text/native are fallbacks; they're tried WITHOUT
        # clearing the field first (clearing left it empty -> no bet).
        strategies = (
            ("slider-cents", lambda: self._native(self.sel.raise_slider, cents)),
            ("native-decimal", lambda: self._native(self.sel.raise_amount, dec)),
            ("native-cents", lambda: self._native(self.sel.raise_amount, cents)),
            ("type-cents", lambda: type_into(self.page.query_selector(self.sel.raise_amount), cents)),
        )
        used = "none"
        for name, fn in strategies:
            try:
                fn()
            except Exception:  # noqa: BLE001
                continue
            self._wait(140)                                    # let the linked field sync before reading
            if self._amount_is(target):                        # exact match within ~2%
                used = name
                break
        if used == "none":                                     # exact set failed -> clean preset (never min)
            used = self._preset_near(target)
        if used != "none":
            self._last_set = self._amount_value()              # the value we'll confirm (for the bet log)
        if not self._set_dumped:                               # one-time calibration snapshot
            self._set_dumped = True
            dump_dom(self.page, f"after-set-amount target={dec} got={self._amount_str()!r} via={used}")
        return used != "none"

    def _native(self, selector: str, value: str) -> None:
        el = self.page.query_selector(selector)
        if el:
            el.evaluate(self._NATIVE_SET, value)

    def _amount_str(self) -> str:
        el = self.page.query_selector(self.sel.raise_amount)
        if not el:
            return ""
        try:
            return el.input_value() or el.get_attribute("value") or ""
        except Exception:  # noqa: BLE001
            try:
                return el.get_attribute("value") or ""
            except Exception:  # noqa: BLE001
                return ""

    def _amount_value(self) -> float | None:
        m = re.search(r"[\d.]+", self._amount_str().replace(",", ""))
        if not m:
            return None
        try:
            return float(m.group(0))
        except ValueError:
            return None

    def _amount_is(self, target: float) -> bool:
        v = self._amount_value()
        if v is None:
            return False
        # accept the slider's nearest-step value (a chip or two off, the table's own granularity)
        # but reject a wrong amount. The absolute allowance SHRINKS for small targets: a flat 2.0
        # would accept the panel's 1.00 min default when the target is a 2.00 bet (a silent min-bet).
        tol = max(0.04 * target, min(2.0, 0.25 * target))
        return abs(v - target) <= tol
