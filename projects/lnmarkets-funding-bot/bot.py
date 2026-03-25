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
from grid_strategy import GridState, sync_grid, calculate_grid_levels
from notifications import (
    notify_trade_opened,
    notify_trade_closed,
    notify_status,
    notify_error,
    notify_kill_switch,
    notify_grid_order_placed,
    notify_grid_recentered,
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
    summary = ""

    # Funding strategy
    if config.FUNDING_ENABLED:
        logger.info("Fetching funding settlements...")
        settlements = await client.get_funding_settlements(limit=config.FUNDING_LOOKBACK)

        if not settlements:
            summary = "No funding data available"
        else:
            analysis = analyze_funding(settlements)

            positions = []
            try:
                positions = await client.get_running_trades()
            except Exception as e:
                logger.warning("Could not fetch positions: %s", e)

            signal = decide_action(analysis, positions, risk.strategy_pnl.get("funding", 0))
            logger.info("Decision: %s — %s (confidence: %.0f%%)", signal.action, signal.reason, signal.confidence * 100)

            if signal.action == "hold":
                summary = f"HOLD: {signal.reason}"
            elif signal.action in ("open_long", "open_short"):
                can, reason = risk.can_trade("funding")
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
    else:
        summary = "FUNDING: disabled"

    # Grid strategy
    if config.GRID_ENABLED:
        try:
            grid_summary = await run_grid_cycle(client, risk)
            summary += f" | GRID: {grid_summary}"
        except Exception as e:
            notify_error(f"Grid cycle error: {e}")
            summary += f" | GRID ERROR: {e}"

    # 7. Status report
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


async def run_grid_cycle(client: LNMClientWrapper, risk: RiskManager) -> str:
    """
    Execute one grid trading cycle.

    Returns:
        Summary string.
    """
    can, reason = risk.can_trade("grid")
    if not can:
        return f"BLOCKED: {reason}"

    # Get current price
    price = await client.get_last_price()

    # Get open limit orders and running trades
    open_orders = await client.get_open_orders()
    running_trades = await client.get_running_trades()

    # Load grid state and sync
    state = GridState.load()
    actions = sync_grid(price, open_orders, running_trades, state)

    if not actions:
        return f"Grid OK — {len(open_orders)} orders active, center: {state.center_price:.2f}"

    placed = 0
    for action in actions:
        if action.action == "recenter":
            # Cancel all existing grid orders and rebuild
            if config.BOT_MODE == "dry":
                logger.info("🏜️ DRY RUN — would recenter grid to %.2f", action.price)
                notify_grid_recentered(state.center_price, action.price)
                state.center_price = action.price
                state.save()
                # Re-sync to get the new placement actions
                new_actions = sync_grid(action.price, [], running_trades, state)
                for a in new_actions:
                    if a.action == "place":
                        logger.info("🏜️ DRY RUN — would place %s limit @ %.2f", a.side, a.price)
                        placed += 1
            else:
                old_center = state.center_price
                await client.cancel_all_orders()
                state.center_price = action.price
                state.levels = []
                state.save()
                notify_grid_recentered(old_center, action.price)
                # Re-sync to place new orders
                new_actions = sync_grid(action.price, [], running_trades, state)
                for a in new_actions:
                    if a.action == "place":
                        try:
                            await client.open_limit_order(
                                side=a.side,
                                price=a.price,
                                margin=config.GRID_MARGIN_PER_ORDER,
                                leverage=config.GRID_LEVERAGE,
                                takeprofit=a.takeprofit,
                                stoploss=a.stoploss,
                            )
                            risk.record_trade("grid")
                            notify_grid_order_placed(a.side, a.price, config.GRID_MARGIN_PER_ORDER)
                            placed += 1
                        except Exception as e:
                            notify_error(f"Grid order failed: {a.side} @ {a.price}: {e}")

        elif action.action == "place":
            if config.BOT_MODE == "dry":
                logger.info(
                    "🏜️ DRY RUN — would place %s limit @ %.2f (%s)",
                    action.side, action.price, action.reason,
                )
                placed += 1
            else:
                try:
                    await client.open_limit_order(
                        side=action.side,
                        price=action.price,
                        margin=config.GRID_MARGIN_PER_ORDER,
                        leverage=config.GRID_LEVERAGE,
                        takeprofit=action.takeprofit,
                        stoploss=action.stoploss,
                    )
                    risk.record_trade("grid")
                    notify_grid_order_placed(action.side, action.price, config.GRID_MARGIN_PER_ORDER)
                    placed += 1
                except Exception as e:
                    notify_error(f"Grid order failed: {action.side} @ {action.price}: {e}")

    # Check for filled grid trades and record P&L
    for trade in running_trades:
        entry = trade.get("entry_price") or trade.get("price", 0)
        pnl = trade.get("pl", 0)
        if pnl != 0:
            # Only record for grid trades (matched by price proximity to grid levels)
            grid_levels = calculate_grid_levels(state.center_price) if state.center_price > 0 else []
            for level in grid_levels:
                if abs(float(entry) - level.price) < 1.0:
                    risk.record_pnl(pnl, "grid")
                    break

    # Save state
    if state.center_price == 0:
        state.center_price = price
    state.save()

    mode = "DRY " if config.BOT_MODE == "dry" else ""
    return f"{mode}Placed {placed} orders, center: {state.center_price:.2f}"


async def print_status(client: LNMClientWrapper, risk: RiskManager):
    """Print current bot and market status."""
    print("\n" + "=" * 60)
    print("🦞 LN Markets Funding Bot — Status")
    print("=" * 60)

    # Risk status
    status = risk.status()
    print(f"\n📊 Risk Manager:")
    print(f"   Date: {status['date']}")
    print(f"   Daily P&L: {status['daily_pnl_sats']:+d} sats (funding: {status['funding_pnl']:+d}, grid: {status['grid_pnl']:+d})")
    print(f"   Trades today: {status['trades_today']} (funding: {status['funding_trades']}, grid: {status['grid_trades']})")
    print(f"   Can trade (funding): {status['can_trade']} ({status['reason']})")
    print(f"   Can trade (grid): {status['can_trade_grid']} ({status['reason_grid']})")
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

    # Grid
    if config.GRID_ENABLED:
        print(f"\n📐 Grid Bot:")
        grid_state = GridState.load()
        if grid_state.center_price > 0:
            print(f"   Center price: {grid_state.center_price:.2f}")
            levels = calculate_grid_levels(grid_state.center_price)
            buy_levels = sorted([l for l in levels if l.side == "buy"], key=lambda l: l.price, reverse=True)
            sell_levels = sorted([l for l in levels if l.side == "sell"], key=lambda l: l.price)
            print(f"   Buy levels: {', '.join(f'{l.price:.2f}' for l in buy_levels)}")
            print(f"   Sell levels: {', '.join(f'{l.price:.2f}' for l in sell_levels)}")
        else:
            print("   Not initialized (will set up on first cycle)")
        try:
            open_orders = await client.get_open_orders()
            print(f"   Open limit orders: {len(open_orders)}")
        except Exception as e:
            print(f"   Error fetching open orders: {e}")
    else:
        print(f"\n📐 Grid Bot: DISABLED")

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
    if config.GRID_ENABLED:
        print(f"   Grid levels: {config.GRID_LEVELS} per side")
        print(f"   Grid spacing: {config.GRID_SPACING_PCT}%")
        print(f"   Grid margin/order: {config.GRID_MARGIN_PER_ORDER} sats")
        print(f"   Grid leverage: {config.GRID_LEVERAGE}x")
        print(f"   Grid daily limit: {config.GRID_DAILY_LOSS_LIMIT_SATS} sats")

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
