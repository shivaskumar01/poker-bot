# PokerNow Bot

A No-Limit Hold'em cash-game bot for **PokerNow**, built for a **consenting home game** —
a table where the other players know a bot is in the lineup — and for **self-play strategy
research**. Plays the full **2-to-10-handed** continuum and adapts to seats joining/leaving
mid-session.

## Responsible use (read this)

- PokerNow's Terms of Service prohibit undisclosed automation. This project targets **disclosed**
  play (everyone consents) and **self-play** testing — the same way poker-AI research is validated.
- **Execution is refused unless `players_consent: true`** in `config.yaml`. Default `mode: observe`
  reads and decides but never clicks.
- There is **no stealth / anti-detection layer** and there will not be one. The "think-time" delay
  exists only to avoid hammering the server and to act at a realistic pace in a disclosed game.

## Layout

```
src/pokerbot/
  io/        Playwright browser, selectors, DOM+log scraper, action executor
  model/     cards, GameState, 2-10 position continuum, hand-history parser
  equity/    eval7 wrapper + multiway Monte-Carlo equity + preflop tables
  opponents/ HUD stats, SQLite store (confidence shrinkage), villain classifier
  strategy/  ranges, preflop/postflop decisions, sizing, mixer, engine pipeline
  extras/    straddle / ante / bomb pot / run-it-twice handling
  runtime/   orchestrator loop, safety (stop-loss/kill-switch/consent), dashboard
tools/       selector_probe (live calibration), selfplay_harness (bb/100 validation)
```

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .[dev]
./.venv/bin/playwright install chromium
```

## Test

```bash
./.venv/bin/pytest
```

## Status

Built bottom-up, each phase ending in a runnable+tested artifact. See
`~/.claude/plans/i-want-to-build-joyful-giraffe.md` for the full plan. Current: core model +
equity engine.
