# PokerNow Bot

A No-Limit Hold'em cash-game bot for **PokerNow**, built for a **consenting home game** and
**self-play research**. It plays the full **2-to-10-handed** continuum, adapts to seats
joining/leaving, **learns each opponent from real hand histories**, and plays an exploitative,
clean-sizing game tuned to how your group actually plays.

## Responsible use (read this)

- PokerNow's Terms of Service prohibit undisclosed automation. This targets **disclosed** play
  (everyone consents) and **self-play** — the way poker-AI research is validated.
- **It will not click anything unless `mode: execute` AND `players_consent: true`** in
  `config.yaml`. Default is `observe` (reads + narrates, never acts).
- There is **no stealth/anti-detection layer**. The think-time delay is only server courtesy.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .[dev]
./.venv/bin/playwright install chromium
./.venv/bin/pytest          # 79 tests
```

## Workflow

**Easiest — the control panel** (set table/mode, Start/Stop, watch the live hand + decision,
see opponent profiles, re-learn from logs, all in one page):
```bash
PYTHONPATH=src ./.venv/bin/python tools/app.py      # opens http://127.0.0.1:8765
```
Or use the individual command-line tools:

**1. Learn your group** (build opponent profiles from PokerNow log exports):
```bash
PYTHONPATH=src ./.venv/bin/python tools/analyze_logs.py    # reads ~/Desktop/Poker learning logs
```
Prints a HUD per player (VPIP/PFR/3bet/AF/fold-to-c-bet/WTSD + archetype) and saves
`data/opponents.sqlite`, which the bot uses live to exploit each person.

**2. Watch it (read-only)** — confirm it reads your table and see its reasoning:
```bash
PYTHONPATH=src ./.venv/bin/python tools/observe.py "<table-url>" --sb 0.25 --bb 0.50
```

**3. Play it live** — defaults to observe; set `mode: execute` + `players_consent: true` in
`config.yaml` to let it act:
```bash
PYTHONPATH=src ./.venv/bin/python tools/play.py "<table-url>"
```
Safety: `stop_loss_bb` / `stop_win_bb` / `max_hands` end the session automatically; **`touch STOP`**
(a file named in `config.yaml`) halts it any time; every decision is logged to `data/hands.jsonl`.

**Validate the strategy offline** (bot vs bot / vs calling-stations, measures bb/100):
```bash
PYTHONPATH=src ./.venv/bin/python tools/selfplay_harness.py 2000 6 --vs-stations
```

## How it plays

- **Preflop:** opens your group's style (pairs/suited/broadway/connectors — no offsuit junk),
  clean sizing (bigger vs loose), **defends by pot-odds** (won't be run over by 3-bets),
  3-bets >=3x, short-stack push/fold.
- **Postflop:** real hand-reading (made / draw / air) + multiway equity; value-bets, semi-bluffs
  *real* draws (open-enders/flush draws, not gutshots), bluffs selectively, checks showdown
  value, **never bluffs the river into a caller**; clean pot-relative sizing with overbets.
- **Exploits the person, not just the odds:** calls down lighter vs aggressive bluffers
  (lag/maniac), tighter vs nits; sizes and bluffs off each villain's tendencies; never raises
  an all-in; commits at low SPR.

## Layout

```
src/pokerbot/
  io/        browser, selectors, scraper (+ preflop reconstruct), executor, log_parser
  model/     cards, GameState, 2-10 position continuum
  equity/    eval7 wrapper, multiway Monte-Carlo, hand-reading (made/draw/air), preflop table
  opponents/ HUD stats (+shrinkage), SQLite store, villain classifier, tracking
  strategy/  ranges, preflop, postflop, sizing, mixer, exploit, engine
  runtime/   config, safety (stop-loss/kill-switch/think-time), orchestrator, self-play
tools/       analyze_logs, observe, play, selfplay_harness, selector_probe, gen_preflop_strength
```

## Status

Complete and runnable. The decision engine + learning + live runtime are done and tested
(79 tests). Heads-up reading is exact; for **multiway** pots and precise 3-bet/4-bet level
detection the live scraper still needs the per-seat bet-chip + in-game LOG selectors (captured
via `tools/selector_probe.py` mid-hand). Run-it-twice and all-ins are handled; antes/straddles
are config-supported. See `~/.claude/plans/i-want-to-build-joyful-giraffe.md` for the full plan.
