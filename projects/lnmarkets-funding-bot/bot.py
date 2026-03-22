#!/usr/bin/env python3
"""
LN Markets Funding Rate Arbitrage Bot 🦞⚡

Main loop:
1. Fetch recent funding settlements
2. Analyze funding rate trend
3. Check risk limits
4. Open/close positions based on strategy
5. Sleep and repeat

Usage:
    python bot.py              # Run continuously
    python bot.py --once       # Run one cycle and exit
    python bot.py --status     # Print current status and exit
"""

import asyncio
import argparse
import logging
import sys
from datetime import datetime, timezone

import config
from lnm_client import LNMClientWrapper
from strategy import analyze_funding, decide_action, calculate_stop_take
from risk_manager import RiskManager
from notifications import (
    notify_trade_opened,
    notify_trade_closed,
    notify_status,
    notify_error,
    notify_kill_switch,
)

# === Logging Setup ===
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE),
    ],
)
logger = logging.getLogger("bot")


async def run_cycle(client: LNMClientWrapper, risk: RiskManager) -> str:
    """
    Execute one trading cycle.

    Returns:
        Summary string of what happened.
    """
    risk.check_new_day()

    # 1. Get funding data
    logger.info("Fetching funding settlements...")
    settlements = await client.get_funding_settlements(limit=config.FUNDING_LOOKBACK)

    if not settlements:
        return "No funding data available"

    # 2. Analyze
    analysis = analyze_funding(settlements)

    # 3. Get current positions
    positions = []
    try:
        positions = await client.get_running_trades()
    except Exception as e:
        logger.warning("Could not fetch positions: %s", e)

    # 4. Decide
    signal = decide_action(analysis, positions, risk.daily_pnl_sats)
    logger.info("Decision: %s — %s (confidence: %.0f%%)", signal.action, signal.reason, signal.confidence * 100)

    # 5. Execute
    if signal.action == "hold":
        summary = f"HOLD: {signal.reason}"

    elif signal.action in ("open_long", "open_short"):
        can, reason = risk.can_trade()
        if not can:
            summary = f"BLOCKED: {reason}"
            logger.warning(summary)
        else:
            side = "buy" if signal.action == "open_long" else "sell"
            summary = await _execute_open(client, risk, side, signal)

    elif signal.action == "close":
        summary = await _execute_close(client, risk, positions, signal)

    else:
        summary = f"Unknown action: {signal.action}"

    # 6. Status report
    risk_status = risk.status()
    notify_status(risk_status, summary)

    return summary


async def _execute_open(
    client: LNMClientWrapper,
    risk: RiskManager,
    side: str,
    signal,
) -> str:
    """Open a new trade."""
    if config.BOT_MODE == "dry":
        logger.info("🏜️ DRY RUN — would open %s position", side)
        risk.record_trade()
        return f"DRY RUN: Would open {side} (funding: {signal.funding_rate:.4f}%)"

    try:
        # Get current price for stop/take calculation
        price = await client.get_last_price()
        stoploss, takeprofit = calculate_stop_take(side, price)

        result = await client.open_trade(
            side=side,
            margin=signal.suggested_margin,
            leverage=signal.suggested_leverage,
            stoploss=stoploss,
            takeprofit=takeprofit,
        )

        risk.record_trade()
        notify_trade_opened(signal, result)

        trade_id = result.get("id", "?")
        return f"OPENED {side.upper()} — ID: {trade_id}, margin: {signal.suggested_margin} sats, leverage: {signal.suggested_leverage}x, SL: {stoploss}, TP: {takeprofit}"

    except Exception as e:
        error_msg = f"Failed to open {side}: {e}"
        notify_error(error_msg)
        return error_msg


async def _execute_close(
    client: LNMClientWrapper,
    risk: RiskManager,
    positions: list[dict],
    signal,
) -> str:
    """Close position(s) that are against the funding trend."""
    if not positions:
        return "No positions to close"

    closed = []
    for pos in positions:
        pos_side = pos.get("side", "")
        is_long = pos_side in ("buy", "b")
        is_short = pos_side in ("sell", "s")

        should_close = False
        if is_long and signal.funding_rate > 0:
            should_close = True
        elif is_short and signal.funding_rate < 0:
            should_close = True

        if not should_close:
            continue

        trade_id = pos.get("id", "")
        if not trade_id:
            continue

        if config.BOT_MODE == "dry":
            pnl = pos.get("pl", 0)
            logger.info("🏜️ DRY RUN — would close trade %s (P&L: %+d sats)", trade_id, pnl)
            risk.record_pnl(pnl)
            closed.append(trade_id)
            continue

        try:
            result = await client.close_trade(trade_id)
            pnl = result.get("pl", pos.get("pl", 0))
            risk.record_pnl(pnl)
            notify_trade_closed(trade_id, signal.reason, pnl)
            closed.append(trade_id)
        except Exception as e:
            notify_error(f"Failed to close {trade_id}: {e}")

    if closed:
        mode = "DRY " if config.BOT_MODE == "dry" else ""
        return f"{mode}CLOSED {len(closed)} position(s): {', '.join(closed)}"
    return "No positions needed closing"


async def print_status(client: LNMClientWrapper, risk: RiskManager):
    """Print current bot and market status."""
    print("\n" + "=" * 60)
    print("🦞 LN Markets Funding Bot — Status")
    print("=" * 60)

    # Risk status
    status = risk.status()
    print(f"\n📊 Risk Manager:")
    print(f"   Date: {status['date']}")
    print(f"   Daily P&L: {status['daily_pnl_sats']:+d} sats")
    print(f"   Trades today: {status['trades_today']}")
    print(f"   Can trade: {status['can_trade']} ({status['reason']})")
    print(f"   Kill switch: {'🛑 ACTIVE' if status['killed'] else '✅ OFF'}")

    # Funding data
    print(f"\n📈 Funding Rate:")
    try:
        settlements = await client.get_funding_settlements(limit=config.FUNDING_LOOKBACK)
        if settlements:
            analysis = analyze_funding(settlements)
            print(f"   Current rate: {analysis.current_rate:.4f}%")
            print(f"   Average rate: {analysis.avg_rate:.4f}%")
            print(f"   Trend: {analysis.trend}")
            print(f"   Consecutive same-sign: {analysis.consecutive_same_sign}")
            print(f"   Strong signal: {'✅' if analysis.is_strong_signal else '❌'}")
        else:
            print("   No settlement data available")
    except Exception as e:
        print(f"   Error fetching funding data: {e}")

    # Positions
    print(f"\n📋 Positions:")
    try:
        positions = await client.get_running_trades()
        if positions:
            for p in positions:
                side = "LONG" if p.get("side") in ("buy", "b") else "SHORT"
                print(f"   {side} — margin: {p.get('margin', '?')} sats, P&L: {p.get('pl', '?')} sats")
        else:
            print("   No open positions")
    except Exception as e:
        print(f"   Error fetching positions: {e}")

    # Config
    print(f"\n⚙️  Config:")
    print(f"   Mode: {config.BOT_MODE.upper()}")
    print(f"   Network: {config.LNM_NETWORK}")
    print(f"   Funding threshold: {config.FUNDING_RATE_THRESHOLD}%")
    print(f"   Max leverage: {config.MAX_LEVERAGE}x")
    print(f"   Margin/trade: {config.MARGIN_PER_TRADE} sats")
    print(f"   Max positions: {config.MAX_OPEN_POSITIONS}")
    print(f"   Daily loss limit: {config.DAILY_LOSS_LIMIT_SATS} sats")
    print(f"   Check interval: {config.CHECK_INTERVAL_SECONDS}s")

    print("\n" + "=" * 60)


async def main():
    parser = argparse.ArgumentParser(description="LN Markets Funding Rate Bot 🦞⚡")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    args = parser.parse_args()

    client = LNMClientWrapper()
    risk = RiskManager()

    try:
        await client.connect()

        if args.status:
            await print_status(client, risk)
            return

        if args.once:
            result = await run_cycle(client, risk)
            logger.info("Single cycle result: %s", result)
            return

        # Continuous loop
        logger.info("🦞 Funding Rate Bot starting (mode: %s, network: %s)", config.BOT_MODE, config.LNM_NETWORK)
        logger.info("Checking every %ds, threshold: %.4f%%", config.CHECK_INTERVAL_SECONDS, config.FUNDING_RATE_THRESHOLD)

        while True:
            try:
                result = await run_cycle(client, risk)
                logger.info("Cycle complete: %s", result)
            except Exception as e:
                notify_error(f"Cycle error: {e}")

            logger.info("Sleeping %ds until next check...", config.CHECK_INTERVAL_SECONDS)
            await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        notify_error(f"Fatal error: {e}")
        raise
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
