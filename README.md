# PokerNow Bot

A No-Limit Hold'em cash-game bot for PokerNow. I built it for a consenting home
game and for self-play research. It handles the full 2-to-10-handed range, adapts
as seats join and leave, learns each opponent from real hand histories, and plays
an exploitative, clean-sizing game tuned to how your group plays.

## API keys

None. The bot drives PokerNow through your own logged-in browser session, so there is
nothing to paste. Table, stakes, and mode settings live in `config.yaml`.

## Responsible use (read this)

- PokerNow's Terms of Service prohibit undisclosed automation. This is for disclosed
  play, where everyone consents, and for self-play, which is how poker-AI research
  gets validated.
- It will not click anything unless `mode: execute` AND `players_consent: true` in
  `config.yaml`. The default is `observe`: it reads and narrates, never acts.
- There is no stealth or anti-detection layer. The think-time delay is only there to
  be polite to the server.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .[dev]
./.venv/bin/playwright install chromium
./.venv/bin/pytest          # 79 tests
```

## Workflow

The easiest way in is the control panel. You set the table and mode, hit Start/Stop,
watch the live hand and the decision, see opponent profiles, and re-learn from logs,
all on one page:
```bash
PYTHONPATH=src ./.venv/bin/python tools/app.py      # opens http://127.0.0.1:8765
```
Or use the individual command-line tools.

1. Learn your group (build opponent profiles from PokerNow log exports):
```bash
PYTHONPATH=src ./.venv/bin/python tools/analyze_logs.py    # reads ~/Desktop/Poker learning logs
```
This prints a HUD per player (VPIP/PFR/3bet/AF/fold-to-c-bet/WTSD plus an archetype)
and saves `data/opponents.sqlite`, which the bot reads live to exploit each person.

2. Watch it, read-only, to confirm it reads your table and to see its reasoning:
```bash
PYTHONPATH=src ./.venv/bin/python tools/observe.py "<table-url>" --sb 0.25 --bb 0.50
```

3. Play it live. It defaults to observe; set `mode: execute` and `players_consent: true`
in `config.yaml` to let it act:
```bash
PYTHONPATH=src ./.venv/bin/python tools/play.py "<table-url>"
```
For safety, `stop_loss_bb` / `stop_win_bb` / `max_hands` end the session on their own,
`touch STOP` (a file named in `config.yaml`) halts it at any time, and every decision
is logged to `data/hands.jsonl`.

Validate the strategy offline (bot vs bot, or vs calling-stations, measured in bb/100):
```bash
PYTHONPATH=src ./.venv/bin/python tools/selfplay_harness.py 2000 6 --vs-stations
```

## How it plays

- Preflop: it opens your group's style (pairs, suited, broadway, connectors, no offsuit
  junk), sizes cleanly (bigger against loose tables), defends by pot-odds so it won't get
  run over by 3-bets, 3-bets at >=3x, and plays push/fold when short.
- Postflop: real hand-reading (made / draw / air) plus multiway equity. It value-bets,
  semi-bluffs real draws (open-enders and flush draws, not gutshots), bluffs selectively,
  checks showdown value, and never bluffs the river into a caller. Sizing is pot-relative
  and includes overbets.
- It exploits the person, not only the odds: it calls down lighter against aggressive
  bluffers (lag/maniac), tighter against nits, sizes and bluffs off each villain's
  tendencies, never raises an all-in, and commits at low SPR.

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

Complete and runnable. The decision engine, the learning, and the live runtime are
done and tested (79 tests). Heads-up reading is exact. For multiway pots and precise
3-bet/4-bet level detection, the live scraper still needs the per-seat bet-chip and
in-game LOG selectors, captured mid-hand via `tools/selector_probe.py`. Run-it-twice
and all-ins are handled, and antes and straddles are config-supported.
