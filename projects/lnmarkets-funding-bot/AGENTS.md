# AGENTS.md — LN Markets Funding Rate Bot

## What Is This?

A Python trading bot that harvests **funding rate payments** on [LN Markets](https://lnmarkets.com) Bitcoin perpetual futures. It doesn't predict price — it positions to collect funding fees as recurring income.

## Strategy (TL;DR)

- **Positive funding rate** → Longs pay shorts → Bot opens a **short** to collect
- **Negative funding rate** → Shorts pay longs → Bot opens a **long** to collect
- **Funding flips** → Bot closes the position to stop paying
- **Weak/unclear signal** → Bot does nothing

Funding settlements happen every 8 hours on LN Markets.

## Architecture

```
bot.py              — Entry point + main loop (continuous, --once, --status)
config.py           — All tunable parameters (loaded from .env)
strategy.py         — Funding rate analysis + trade decision logic
lnm_client.py       — LN Markets API wrapper (official Python SDK v3)
risk_manager.py     — Daily P&L tracking, position limits, kill switch
notifications.py    — Trade event logging
```

## Key Design Decisions

- **Dry-run by default** (`BOT_MODE=dry`) — logs what it would do, doesn't trade
- **Testnet by default** (`LNM_NETWORK=testnet4`) — flip to `mainnet` when ready
- **Conservative defaults** — 3x leverage, 2% stop-loss, 50k sats daily loss limit
- **Isolated margin** — each trade is independent, no cross-margin risk
- **Rate limit aware** — 1.1s sleep between API calls (limit is 1 req/sec)

## How To Run

```bash
# Setup (one-time)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Edit .env with API credentials

# Run
.venv/bin/python bot.py --status    # Check connection + current state
.venv/bin/python bot.py --once      # Single cycle (good for cron)
.venv/bin/python bot.py             # Continuous loop
```

## Configuration

All in `config.py`, loaded from `.env`:

| Parameter | Default | What it does |
|---|---|---|
| `FUNDING_RATE_THRESHOLD` | 0.01% | Min rate to trigger entry |
| `MIN_CONSECUTIVE_SAME_SIGN` | 3 | Consecutive same-sign settlements needed |
| `MAX_LEVERAGE` | 3x | Position leverage |
| `MARGIN_PER_TRADE` | 10,000 sats | Margin per position |
| `STOP_LOSS_PCT` | 2% | Stop-loss distance from entry |
| `TAKE_PROFIT_PCT` | 1.5% | Take-profit distance from entry |
| `MAX_OPEN_POSITIONS` | 3 | Max simultaneous positions |
| `DAILY_LOSS_LIMIT_SATS` | 50,000 | Daily loss hard stop |
| `CHECK_INTERVAL_SECONDS` | 300 | Loop interval (5 min) |

## Risk Controls

- **Daily loss limit** — auto-shuts down if daily P&L exceeds limit
- **Kill switch** — `risk_manager.kill()` stops all trading until next day
- **Max position cap** — won't open more than N positions
- **Mandatory stop-loss** — every trade gets SL + TP on entry
- **State persisted** — `risk_state.json` survives restarts

## Dependencies

- `lnmarkets-sdk` (official v3 Python SDK)
- `python-dotenv`
- Python 3.10+

## Files You Shouldn't Commit

- `.env` — API secrets
- `risk_state.json` — runtime state
- `trades.log` — trade history log

## Status

🚧 **Pre-deployment** — code complete, needs `python3.11-venv` installed on host to set up virtualenv, then API keys configured. Currently set to dry-run on testnet.

## Owner

Built by Chad 🦞 for funding rate harvesting on LN Markets.
