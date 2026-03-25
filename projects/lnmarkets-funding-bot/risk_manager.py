"""
Risk management: tracks daily P&L per strategy, enforces limits, kill switch.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent / "risk_state.json"

STRATEGY_LIMITS = {
    "funding": config.DAILY_LOSS_LIMIT_SATS,
    "grid": config.GRID_DAILY_LOSS_LIMIT_SATS,
}


class RiskManager:
    """Tracks daily P&L per strategy and enforces risk limits."""

    def __init__(self):
        self.strategy_pnl: dict[str, int] = {"funding": 0, "grid": 0}
        self.strategy_trades: dict[str, int] = {"funding": 0, "grid": 0}
        self.date: str = self._today()
        self.killed: bool = False
        self._load_state()

    @property
    def daily_pnl_sats(self) -> int:
        """Total P&L across all strategies."""
        return sum(self.strategy_pnl.values())

    @property
    def trades_today(self) -> int:
        """Total trades across all strategies."""
        return sum(self.strategy_trades.values())

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load_state(self):
        """Load persisted risk state, reset if new day."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                if data.get("date") == self._today():
                    # Load per-strategy data (backward compatible)
                    self.strategy_pnl = data.get("strategy_pnl", {
                        "funding": data.get("daily_pnl_sats", 0),
                        "grid": 0,
                    })
                    self.strategy_trades = data.get("strategy_trades", {
                        "funding": data.get("trades_today", 0),
                        "grid": 0,
                    })
                    self.killed = data.get("killed", False)
                    logger.info(
                        "Loaded risk state: funding_pnl=%d grid_pnl=%d trades=%d killed=%s",
                        self.strategy_pnl.get("funding", 0),
                        self.strategy_pnl.get("grid", 0),
                        self.trades_today,
                        self.killed,
                    )
                else:
                    logger.info("New day — resetting risk state")
                    self._reset_daily()
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt risk state file, resetting")
                self._reset_daily()
        else:
            self._reset_daily()

    def _reset_daily(self):
        """Reset counters for a new trading day."""
        self.strategy_pnl = {"funding": 0, "grid": 0}
        self.strategy_trades = {"funding": 0, "grid": 0}
        self.date = self._today()
        self.killed = False
        self._save_state()

    def _save_state(self):
        """Persist current risk state."""
        data = {
            "date": self.date,
            "strategy_pnl": self.strategy_pnl,
            "strategy_trades": self.strategy_trades,
            "daily_pnl_sats": self.daily_pnl_sats,
            "trades_today": self.trades_today,
            "killed": self.killed,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        STATE_FILE.write_text(json.dumps(data, indent=2))

    def check_new_day(self):
        """Reset if the day changed."""
        if self._today() != self.date:
            logger.info("Day rolled over, resetting risk state")
            self._reset_daily()

    def can_trade(self, strategy: str = "funding") -> tuple[bool, str]:
        """
        Check if trading is allowed for a given strategy.

        Returns:
            (allowed, reason)
        """
        self.check_new_day()

        if self.killed:
            return False, "Kill switch active — bot was manually stopped"

        limit = STRATEGY_LIMITS.get(strategy, config.DAILY_LOSS_LIMIT_SATS)
        pnl = self.strategy_pnl.get(strategy, 0)
        if pnl <= -limit:
            return False, f"{strategy} daily loss limit hit: {pnl} sats (limit: -{limit})"

        return True, "OK"

    def record_trade(self, strategy: str = "funding", pnl_sats: int = 0):
        """Record a trade execution."""
        self.strategy_trades[strategy] = self.strategy_trades.get(strategy, 0) + 1
        self._save_state()
        logger.info("Trade recorded for %s (#%d today)", strategy, self.strategy_trades[strategy])

    def record_pnl(self, pnl_sats: int, strategy: str = "funding"):
        """Record realized P&L from a closed trade."""
        self.strategy_pnl[strategy] = self.strategy_pnl.get(strategy, 0) + pnl_sats
        self._save_state()
        logger.info(
            "P&L recorded (%s): %+d sats (strategy total: %+d, daily total: %+d)",
            strategy,
            pnl_sats,
            self.strategy_pnl[strategy],
            self.daily_pnl_sats,
        )

        limit = STRATEGY_LIMITS.get(strategy, config.DAILY_LOSS_LIMIT_SATS)
        if self.strategy_pnl[strategy] <= -limit:
            logger.warning("⚠️ %s DAILY LOSS LIMIT REACHED — stopping %s trades", strategy.upper(), strategy)

    def kill(self):
        """Emergency stop — no more trades until manual reset or new day."""
        self.killed = True
        self._save_state()
        logger.warning("🛑 Kill switch activated")

    def reset_kill(self):
        """Reset the kill switch."""
        self.killed = False
        self._save_state()
        logger.info("Kill switch reset")

    def status(self) -> dict:
        """Return current risk status."""
        self.check_new_day()
        can_funding, reason_funding = self.can_trade("funding")
        can_grid, reason_grid = self.can_trade("grid")
        return {
            "date": self.date,
            "daily_pnl_sats": self.daily_pnl_sats,
            "trades_today": self.trades_today,
            "funding_pnl": self.strategy_pnl.get("funding", 0),
            "grid_pnl": self.strategy_pnl.get("grid", 0),
            "funding_trades": self.strategy_trades.get("funding", 0),
            "grid_trades": self.strategy_trades.get("grid", 0),
            "can_trade": can_funding,
            "can_trade_grid": can_grid,
            "reason": reason_funding,
            "reason_grid": reason_grid,
            "killed": self.killed,
        }
