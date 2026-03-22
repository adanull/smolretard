"""
Risk management: tracks daily P&L, enforces limits, kill switch.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent / "risk_state.json"


class RiskManager:
    """Tracks daily P&L and enforces risk limits."""

    def __init__(self):
        self.daily_pnl_sats: int = 0
        self.trades_today: int = 0
        self.date: str = self._today()
        self.killed: bool = False
        self._load_state()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load_state(self):
        """Load persisted risk state, reset if new day."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                if data.get("date") == self._today():
                    self.daily_pnl_sats = data.get("daily_pnl_sats", 0)
                    self.trades_today = data.get("trades_today", 0)
                    self.killed = data.get("killed", False)
                    logger.info(
                        "Loaded risk state: pnl=%d sats, trades=%d, killed=%s",
                        self.daily_pnl_sats,
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
        self.daily_pnl_sats = 0
        self.trades_today = 0
        self.date = self._today()
        self.killed = False
        self._save_state()

    def _save_state(self):
        """Persist current risk state."""
        data = {
            "date": self.date,
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

    def can_trade(self) -> tuple[bool, str]:
        """
        Check if trading is allowed right now.

        Returns:
            (allowed, reason)
        """
        self.check_new_day()

        if self.killed:
            return False, "Kill switch active — bot was manually stopped"

        if self.daily_pnl_sats <= -config.DAILY_LOSS_LIMIT_SATS:
            return False, f"Daily loss limit hit: {self.daily_pnl_sats} sats (limit: -{config.DAILY_LOSS_LIMIT_SATS})"

        return True, "OK"

    def record_trade(self, pnl_sats: int = 0):
        """Record a trade execution."""
        self.trades_today += 1
        self._save_state()
        logger.info("Trade recorded (#%d today)", self.trades_today)

    def record_pnl(self, pnl_sats: int):
        """Record realized P&L from a closed trade."""
        self.daily_pnl_sats += pnl_sats
        self._save_state()
        logger.info(
            "P&L recorded: %+d sats (daily total: %+d sats)",
            pnl_sats,
            self.daily_pnl_sats,
        )

        if self.daily_pnl_sats <= -config.DAILY_LOSS_LIMIT_SATS:
            logger.warning("⚠️ DAILY LOSS LIMIT REACHED — stopping trades")

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
        can, reason = self.can_trade()
        return {
            "date": self.date,
            "daily_pnl_sats": self.daily_pnl_sats,
            "trades_today": self.trades_today,
            "daily_loss_limit": config.DAILY_LOSS_LIMIT_SATS,
            "can_trade": can,
            "reason": reason,
            "killed": self.killed,
        }
