"""
Simple notification helper — writes to log and stdout.
For Telegram integration, this bot is designed to be run
via OpenClaw cron, which handles notifications natively.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def notify_trade_opened(signal, trade_result: dict):
    """Log a trade open event."""
    msg = (
        f"📈 TRADE OPENED\n"
        f"Action: {signal.action}\n"
        f"Reason: {signal.reason}\n"
        f"Funding rate: {signal.funding_rate:.4f}%\n"
        f"Confidence: {signal.confidence:.0%}\n"
        f"Trade ID: {trade_result.get('id', 'N/A')}\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}"
    )
    logger.info(msg)
    print(msg)


def notify_trade_closed(trade_id: str, reason: str, pnl_sats: int):
    """Log a trade close event."""
    emoji = "✅" if pnl_sats >= 0 else "❌"
    msg = (
        f"{emoji} TRADE CLOSED\n"
        f"Trade ID: {trade_id}\n"
        f"Reason: {reason}\n"
        f"P&L: {pnl_sats:+d} sats\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}"
    )
    logger.info(msg)
    print(msg)


def notify_status(risk_status: dict, analysis_summary: str):
    """Log periodic status update."""
    msg = (
        f"📊 BOT STATUS\n"
        f"Daily P&L: {risk_status['daily_pnl_sats']:+d} sats\n"
        f"Trades today: {risk_status['trades_today']}\n"
        f"Can trade: {risk_status['can_trade']}\n"
        f"Analysis: {analysis_summary}\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}"
    )
    logger.info(msg)
    print(msg)


def notify_error(error: str):
    """Log an error."""
    msg = f"🚨 BOT ERROR: {error}"
    logger.error(msg)
    print(msg)


def notify_kill_switch(reason: str):
    """Log kill switch activation."""
    msg = f"🛑 KILL SWITCH: {reason}"
    logger.critical(msg)
    print(msg)


def notify_grid_order_placed(side: str, price: float, margin: int):
    """Log a grid limit order placement."""
    msg = (
        f"📐 GRID ORDER PLACED\n"
        f"Side: {side.upper()}\n"
        f"Price: {price:.2f}\n"
        f"Margin: {margin} sats\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}"
    )
    logger.info(msg)
    print(msg)


def notify_grid_recentered(old_center: float, new_center: float):
    """Log grid recenter event."""
    msg = (
        f"📐 GRID RECENTERED\n"
        f"Old center: {old_center:.2f}\n"
        f"New center: {new_center:.2f}\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}"
    )
    logger.info(msg)
    print(msg)
