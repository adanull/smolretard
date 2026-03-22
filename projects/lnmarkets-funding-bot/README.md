# LN Markets Funding Rate Arbitrage Bot 🦞⚡

A Python bot that harvests funding rate payments on LN Markets futures.

## Strategy

When the funding rate is significantly positive → open a **short** (shorts get paid).
When the funding rate is significantly negative → open a **long** (longs get paid).

The bot doesn't try to predict price direction — it collects funding payments as recurring income, using tight stop-losses to limit directional risk.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy the example config:
   ```bash
   cp .env.example .env
   ```

3. Fill in your LN Markets API credentials in `.env`

4. (Optional) Adjust strategy parameters in `config.py`

5. Run the bot:
   ```bash
   python bot.py
   ```

## Configuration

See `config.py` for all tunable parameters:
- `FUNDING_RATE_THRESHOLD` — minimum absolute funding rate to enter a position (default: 0.01%)
- `MAX_LEVERAGE` — maximum leverage (default: 3x)
- `MARGIN_PER_TRADE` — sats per position (default: 10,000)
- `STOP_LOSS_PCT` — stop-loss as % of entry price (default: 2%)
- `TAKE_PROFIT_PCT` — take-profit as % of entry price (default: 1.5%)
- `CHECK_INTERVAL_SECONDS` — how often to check funding rate (default: 300 = 5 min)
- `MAX_OPEN_POSITIONS` — max simultaneous positions (default: 3)
- `DAILY_LOSS_LIMIT_SATS` — hard stop for the day (default: 50,000 sats)

## Architecture

```
bot.py              — Main loop: check funding → decide → trade → sleep
config.py           — Strategy parameters + risk limits
lnm_client.py       — LN Markets API wrapper (uses official SDK v3)
strategy.py         — Funding rate analysis + entry/exit logic
risk_manager.py     — Position limits, daily P&L tracking, kill switch
notifications.py    — Telegram alerts via OpenClaw (optional)
```

## Safety Features

- Daily loss limit with automatic shutdown
- Max position count limit
- Mandatory stop-loss on every trade
- Dry-run mode (paper trading) by default
- All trades logged to `trades.log`

## Requirements

- Python 3.10+
- LN Markets account with API access
- API key with futures trading permissions
