"""
Strategy and risk configuration for the funding rate bot.
Adjust these values to match your risk tolerance.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# === API Credentials ===
LNM_API_KEY = os.getenv("LNM_API_KEY", "")
LNM_API_SECRET = os.getenv("LNM_API_SECRET", "")
LNM_API_PASSPHRASE = os.getenv("LNM_API_PASSPHRASE", "")
LNM_NETWORK = os.getenv("LNM_NETWORK", "testnet4")

# === Bot Mode ===
# "dry" = paper trading (logs trades but doesn't execute)
# "live" = real trading
BOT_MODE = os.getenv("BOT_MODE", "dry")

# === Strategy Parameters ===

# Minimum absolute funding rate to trigger a position (in %)
# e.g., 0.01 means only trade when |funding_rate| > 0.01%
FUNDING_RATE_THRESHOLD = 0.01

# Number of recent funding settlements to analyze for trend
FUNDING_LOOKBACK = 8

# Minimum consecutive same-sign settlements to confirm trend
MIN_CONSECUTIVE_SAME_SIGN = 3

# === Position Sizing ===

# Margin per trade in sats
MARGIN_PER_TRADE = 10_000

# Maximum leverage (keep conservative for funding harvesting)
MAX_LEVERAGE = 3

# === Risk Management ===

# Stop-loss as percentage of entry price
STOP_LOSS_PCT = 2.0

# Take-profit as percentage of entry price
TAKE_PROFIT_PCT = 1.5

# Maximum number of open positions at once
MAX_OPEN_POSITIONS = 3

# Daily loss limit in sats — bot shuts down if exceeded
DAILY_LOSS_LIMIT_SATS = 50_000

# === Timing ===

# How often to check funding rate and manage positions (seconds)
CHECK_INTERVAL_SECONDS = 300  # 5 minutes

# Funding settlements happen every 8 hours on LN Markets
# The bot checks more frequently to position before settlement
FUNDING_SETTLEMENT_INTERVAL_HOURS = 8

# === Logging ===
LOG_FILE = "trades.log"
LOG_LEVEL = "INFO"
