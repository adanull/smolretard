"""
LN Markets API client wrapper using the official ln-markets Python SDK.
Handles connection management and provides a clean async interface.

The SDK is synchronous (requests-based), so we wrap calls with
asyncio.to_thread to keep the bot's async architecture.
"""

import asyncio
import json
import logging
from typing import Optional

from lnmarkets import rest

import config

logger = logging.getLogger(__name__)


def _parse(response: str) -> dict | list:
    """Parse JSON response string from the SDK."""
    try:
        return json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return response


class LNMClientWrapper:
    """Manages the LN Markets client and provides trading methods."""

    def __init__(self):
        self._client: Optional[rest.LNMarketsRest] = None

    async def connect(self):
        """Initialize the REST client."""
        options = {
            "key": config.LNM_API_KEY,
            "secret": config.LNM_API_SECRET,
            "passphrase": config.LNM_API_PASSPHRASE,
            "network": config.LNM_NETWORK,
        }
        self._client = rest.LNMarketsRest(**options)
        logger.info("Connected to LN Markets (%s)", config.LNM_NETWORK)

    async def disconnect(self):
        """Clean up (no persistent connection to close with REST)."""
        self._client = None
        logger.info("Disconnected from LN Markets")

    async def _call(self, method, *args, **kwargs):
        """Run a synchronous SDK call in a thread and respect rate limit."""
        result = await asyncio.to_thread(method, *args, **kwargs)
        await asyncio.sleep(1.1)  # Rate limit: 1 req/sec
        return _parse(result)

    # === Public Endpoints ===

    async def get_ticker(self) -> dict:
        """Get current futures ticker (price, funding rate, etc.)."""
        return await self._call(self._client.futures_get_ticker)

    async def get_funding_settlements(self, limit: int = 10) -> list[dict]:
        """
        Get recent funding/carry fee history.
        Uses the futures carry-fees endpoint which returns funding fee records.
        """
        result = await self._call(self._client.futures_carry_fees, {"limit": limit})
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return [result] if result else []

    async def get_last_price(self) -> float:
        """Get the current BTC/USD price."""
        result = await self._call(self._client.get_oracle_last, {})
        if isinstance(result, dict):
            return float(result.get("lastPrice", result.get("last_price", 0)))
        if isinstance(result, list) and len(result) > 0:
            item = result[0]
            if isinstance(item, dict):
                return float(item.get("lastPrice", item.get("last_price", 0)))
            return float(item)
        raise ValueError(f"Could not parse last price from: {result}")

    # === Account ===

    async def get_account(self) -> dict:
        """Get account info (balance, etc.)."""
        return await self._call(self._client.get_user)

    async def get_balance(self) -> int:
        """Get account balance in sats."""
        account = await self.get_account()
        return account.get("balance", 0)

    # === Futures Trading ===

    async def get_running_trades(self) -> list[dict]:
        """Get all currently running (open) trades."""
        result = await self._call(self._client.futures_get_trades, {"type": "running"})
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return []

    async def get_open_orders(self) -> list[dict]:
        """Get unfilled limit orders (open but not yet running)."""
        result = await self._call(self._client.futures_get_trades, {"type": "open"})
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return []

    async def get_closed_trades(self, limit: int = 20) -> list[dict]:
        """Get recently closed trades."""
        result = await self._call(
            self._client.futures_get_trades,
            {"type": "closed", "limit": limit},
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return []

    async def open_trade(
        self,
        side: str,
        margin: int,
        leverage: int,
        stoploss: Optional[float] = None,
        takeprofit: Optional[float] = None,
    ) -> dict:
        """
        Open a new futures trade (market order).

        Args:
            side: "b" (long/buy) or "s" (short/sell)
            margin: margin in sats
            leverage: leverage multiplier
            stoploss: stop-loss price (optional)
            takeprofit: take-profit price (optional)
        """
        # Normalize side to API format
        if side in ("buy", "long"):
            side = "b"
        elif side in ("sell", "short"):
            side = "s"

        params = {
            "type": "m",  # market order
            "side": side,
            "margin": margin,
            "leverage": leverage,
        }
        if stoploss is not None:
            params["stoploss"] = stoploss
        if takeprofit is not None:
            params["takeprofit"] = takeprofit

        result = await self._call(self._client.futures_new_trade, params)
        return result

    async def open_limit_order(
        self,
        side: str,
        price: float,
        margin: int,
        leverage: int,
        stoploss: Optional[float] = None,
        takeprofit: Optional[float] = None,
    ) -> dict:
        """
        Place a limit order on futures.

        Args:
            side: "b" (long/buy) or "s" (short/sell)
            price: limit price
            margin: margin in sats
            leverage: leverage multiplier
            stoploss: stop-loss price (optional)
            takeprofit: take-profit price (optional)
        """
        if side in ("buy", "long"):
            side = "b"
        elif side in ("sell", "short"):
            side = "s"

        params = {
            "type": "l",  # limit order
            "side": side,
            "price": price,
            "margin": margin,
            "leverage": leverage,
        }
        if stoploss is not None:
            params["stoploss"] = stoploss
        if takeprofit is not None:
            params["takeprofit"] = takeprofit

        result = await self._call(self._client.futures_new_trade, params)
        return result

    async def cancel_order(self, trade_id: str) -> dict:
        """Cancel an unfilled limit order."""
        return await self._call(self._client.futures_cancel, {"id": trade_id})

    async def cancel_all_orders(self) -> None:
        """Cancel all unfilled limit orders."""
        await self._call(self._client.futures_cancel_all)

    async def close_trade(self, trade_id: str) -> dict:
        """Close a specific trade by ID."""
        return await self._call(self._client.futures_close, {"id": trade_id})

    async def update_stoploss(self, trade_id: str, value: float) -> dict:
        """Update stop-loss for a trade."""
        return await self._call(
            self._client.futures_update_trade,
            {"id": trade_id, "type": "stoploss", "value": value},
        )

    async def update_takeprofit(self, trade_id: str, value: float) -> dict:
        """Update take-profit for a trade."""
        return await self._call(
            self._client.futures_update_trade,
            {"id": trade_id, "type": "takeprofit", "value": value},
        )

    async def get_funding_fees(self, limit: int = 20) -> list[dict]:
        """Get funding/carry fees paid/received on positions."""
        result = await self._call(self._client.futures_carry_fees, {"limit": limit})
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return []
