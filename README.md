# CRWarBot

Telegram bot for one Clash Royale clan. Tracks whether everyone used their four
river race attacks, nags the ones who did not, and keeps medal statistics per
war, per season and all time.

## What it does

- Polls `currentriverrace` every five minutes and stores a snapshot whenever a
  player's medals or attack count moves.
- Posts two reminders per war day, 16 hours and 4 hours before the daily reset,
  listing who still owes attacks. Players who ran `/link` get pinged by mention.
- Backfills `riverracelog` on startup, so statistics cover roughly the last ten
  races from the very first run.
- Ranks the clan by medals per war with a configurable penalty for missed
  attacks, and tracks pure attendance separately via `/discipline`.

## Commands

| Command | Description |
|---|---|
| `/link <nick\|tag>` | Link your Telegram account to a clan member |
| `/unlink`, `/whoami` | Manage the link |
| `/today` | Who has not played yet today |
| `/war` | Medals and attacks in the current race |
| `/me [period]`, `/stats <nick> [period]` | Player statistics |
| `/rating [period] [avg\|total]` | Clan leaderboard |
| `/discipline [period]` | Percentage of attacks used |
| `/roster` | Who is linked and who is not |

`period` is `war` (default), `season`, `all`, or `2026-01-01..2026-03-01`.

## Run locally

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
cp .env.example .env   # fill in tokens, clan tag, chat id
.venv/bin/python -m pytest
.venv/bin/python -m crwarbot.bot.main
```

The Supercell API token is bound to the requesting IP address — see
[deploy/DEPLOY.md](deploy/DEPLOY.md).

## Layout

```
src/crwarbot/
  api/       Supercell client, response models, rate limiter
  db/        connection, migrations runner, all SQL
  domain/    pure logic: period math, day rollup, rating formulas, nick matching
  worker/    poll loop, reminder dispatch, race log backfill
  bot/       aiogram handlers, message formatting, mentions
```

`domain/` knows nothing about HTTP, SQL or Telegram, which is why the rating
formulas and reminder timing are testable without mocks.
