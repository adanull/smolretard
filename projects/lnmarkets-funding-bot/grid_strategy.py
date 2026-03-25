"""
Grid trading strategy for LN Markets isolated futures.

Places limit buy orders below current price and limit sell orders above.
When a buy fills and price rises back, the position profits. When a sell fills
and price drops back, same thing. Captures the spread in ranging markets.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent / "grid_state.json"


@dataclass
class GridLevel:
    """A single grid level."""
    side: str  # "buy" or "sell"
    price: float
    takeprofit: float = 0.0  # TP at grid center
    stoploss: float = 0.0  # SL at outer bound
    order_id: str | None = None  # LNM trade ID if order is placed
    filled: bool = False


@dataclass
class GridAction:
    """An action the grid bot needs to take."""
    action: str  # "place", "cancel", "recenter"
    side: str = ""
    price: float = 0.0
    takeprofit: float = 0.0
    stoploss: float = 0.0
    order_id: str = ""
    reason: str = ""


@dataclass
class GridState:
    """Persisted grid state."""
    center_price: float = 0.0
    levels: list[dict] = field(default_factory=list)

    def save(self):
        data = {
            "center_price": self.center_price,
            "levels": self.levels,
        }
        STATE_FILE.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> "GridState":
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                return cls(
                    center_price=data.get("center_price", 0.0),
                    levels=data.get("levels", []),
                )
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt grid state, starting fresh")
        return cls()


def calculate_grid_levels(center_price: float) -> list[GridLevel]:
    """
    Calculate grid levels around a center price.

    Returns buy levels below and sell levels above.
    """
    spacing = config.GRID_SPACING_PCT / 100.0
    levels = []

    # Snap helper
    def snap(v: float) -> float:
        return round(v * 2) / 2

    center_snapped = snap(center_price)
    # SL at one level beyond the outermost grid line
    outer_sl_distance = spacing * (config.GRID_LEVELS + 1)

    for i in range(1, config.GRID_LEVELS + 1):
        # Buy levels below current price — TP at center, SL below outer bound
        buy_price = snap(center_price * (1 - spacing * i))
        buy_sl = snap(center_price * (1 - outer_sl_distance))
        levels.append(GridLevel(side="buy", price=buy_price, takeprofit=center_snapped, stoploss=buy_sl))

        # Sell levels above current price — TP at center, SL above outer bound
        sell_price = snap(center_price * (1 + spacing * i))
        sell_sl = snap(center_price * (1 + outer_sl_distance))
        levels.append(GridLevel(side="sell", price=sell_price, takeprofit=center_snapped, stoploss=sell_sl))

    return levels


def sync_grid(
    current_price: float,
    open_orders: list[dict],
    running_trades: list[dict],
    state: GridState,
) -> list[GridAction]:
    """
    Compare desired grid state with actual orders and return needed actions.

    Args:
        current_price: current BTC/USD price
        open_orders: unfilled limit orders from LNM
        running_trades: filled/running positions from LNM
        state: persisted grid state

    Returns:
        List of actions to execute.
    """
    actions = []

    # Check if we need to recenter the grid
    if state.center_price > 0 and config.GRID_RECENTER:
        spacing = config.GRID_SPACING_PCT / 100.0
        outer_distance = spacing * config.GRID_LEVELS
        upper_bound = state.center_price * (1 + outer_distance)
        lower_bound = state.center_price * (1 - outer_distance)

        if current_price > upper_bound or current_price < lower_bound:
            logger.info(
                "Price %.2f outside grid bounds [%.2f, %.2f] — recentering",
                current_price, lower_bound, upper_bound,
            )
            actions.append(GridAction(
                action="recenter",
                price=current_price,
                reason=f"Price moved outside grid bounds (was centered at {state.center_price:.2f})",
            ))
            return actions

    # First time or after recenter — set up grid from scratch
    if state.center_price == 0:
        state.center_price = round(current_price * 2) / 2
        desired_levels = calculate_grid_levels(current_price)
        for level in desired_levels:
            actions.append(GridAction(
                action="place",
                side=level.side,
                price=level.price,
                takeprofit=level.takeprofit,
                stoploss=level.stoploss,
                reason=f"Initial grid: {level.side} at {level.price:.2f}",
            ))
        return actions

    # Normal sync — check which levels are missing orders
    desired_levels = calculate_grid_levels(state.center_price)

    # Build a set of prices that already have open orders
    open_prices = set()
    for order in open_orders:
        price = order.get("price", 0)
        if price:
            open_prices.add(round(float(price), 2))

    # Place orders for missing levels
    for level in desired_levels:
        if level.price not in open_prices:
            # Check this level isn't already a running (filled) trade
            already_running = False
            for trade in running_trades:
                entry = trade.get("entry_price") or trade.get("price", 0)
                if abs(float(entry) - level.price) < 1.0:  # within $1
                    already_running = True
                    break

            if not already_running:
                actions.append(GridAction(
                    action="place",
                    side=level.side,
                    price=level.price,
                    takeprofit=level.takeprofit,
                    stoploss=level.stoploss,
                    reason=f"Missing grid level: {level.side} at {level.price:.2f}",
                ))

    return actions
