"""
LN Markets API client wrapper using the official SDK v3.
Handles connection management and provides a clean interface.
"""

import asyncio
import logging
from typing import Optional

from lnmarkets_sdk.v3.http.client import APIAuthContext, APIClientConfig, LNMClient
from lnmarkets_sdk.v3.models.futures_data import GetFundingSettlementsParams
from lnmarkets_sdk.v3.models.futures_isolated import (
    CancelTradeParams,
    FuturesOrder,
    GetClosedTradesParams,
    GetIsolatedFundingFeesParams,
)

import config

logger = logging.getLogger(__name__)


def _build_config() -> APIClientConfig:
    """Build API client config from environment."""
    auth = None
    if config.LNM_API_KEY and config.LNM_API_SECRET and config.LNM_API_PASSPHRASE:
        auth = APIAuthContext(
            key=config.LNM_API_KEY,
            secret=config.LNM_API_SECRET,
            passphrase=config.LNM_API_PASSPHRASE,
        )
    return APIClientConfig(
        authentication=auth,
        network=config.LNM_NETWORK,
        timeout=30.0,
    )


class LNMClientWrapper:
    """Manages the LN Markets client lifecycle and provides trading methods."""

    def __init__(self):
        self._config = _build_config()
        self._client: Optional[LNMClient] = None

    async def connect(self):
        """Open the client connection."""
        self._client = LNMClient(self._config)
        await self._client.__aenter__()
        logger.info("Connected to LN Markets (%s)", config.LNM_NETWORK)

    async def disconnect(self):
        """Close the client connection."""
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
            logger.info("Disconnected from LN Markets")

    async def _sleep(self):
        """Respect rate limit: 1 req/sec."""
        await asyncio.sleep(1.1)

    # === Public Endpoints ===

    async def get_ticker(self) -> dict:
        """Get current futures ticker (price, funding rate, etc.)."""
        result = await self._client.futures.get_ticker()
        await self._sleep()
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def get_funding_settlements(self, limit: int = 10) -> list[dict]:
        """Get recent funding settlement history."""
        params = GetFundingSettlementsParams(limit=limit)
        result = await self._client.futures.get_funding_settlements(params)
        await self._sleep()
        data = result.data if hasattr(result, "data") else result
        return [s.model_dump() if hasattr(s, "model_dump") else s for s in data]

    async def get_last_price(self) -> float:
        """Get the current BTC/USD price."""
        result = await self._client.oracle.get_last_price()
        await self._sleep()
        if result and len(result) > 0:
            price_obj = result[0]
            return price_obj.last_price if hasattr(price_obj, "last_price") else float(price_obj)
        raise ValueError("Could not fetch last price")

    # === Account ===

    async def get_account(self) -> dict:
        """Get account info (balance, etc.)."""
        result = await self._client.account.get_account()
        await self._sleep()
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def get_balance(self) -> int:
        """Get account balance in sats."""
        account = await self.get_account()
        return account.get("balance", 0)

    # === Isolated Futures Trading ===

    async def get_running_trades(self) -> list[dict]:
        """Get all currently running (open) isolated trades."""
        result = await self._client.futures.isolated.get_running_trades()
        await self._sleep()
        return [t.model_dump() if hasattr(t, "model_dump") else t for t in result]

    async def open_trade(
        self,
        side: str,
        margin: int,
        leverage: int,
        stoploss: Optional[float] = None,
        takeprofit: Optional[float] = None,
    ) -> dict:
        """
        Open a new isolated futures trade (market order).

        Args:
            side: "buy" (long) or "sell" (short)
            margin: margin in sats
            leverage: leverage multiplier
            stoploss: stop-loss price (optional)
            takeprofit: take-profit price (optional)
        """
        params_dict = {
            "type": "market",
            "side": side,
            "margin": margin,
            "leverage": leverage,
        }
        if stoploss is not None:
            params_dict["stoploss"] = stoploss
        if takeprofit is not None:
            params_dict["takeprofit"] = takeprofit

        params = FuturesOrder(**params_dict)
        result = await self._client.futures.isolated.new_trade(params)
        await self._sleep()
        return result.model_dump() if hasattr(result, "model_dump") else result

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
        Place a limit order on isolated futures.

        Args:
            side: "buy" or "sell"
            price: limit price
            margin: margin in sats
            leverage: leverage multiplier
            stoploss: stop-loss price (optional)
            takeprofit: take-profit price (optional)
        """
        params_dict = {
            "type": "limit",
            "side": side,
            "price": price,
            "margin": margin,
            "leverage": leverage,
        }
        if stoploss is not None:
            params_dict["stoploss"] = stoploss
        if takeprofit is not None:
            params_dict["takeprofit"] = takeprofit

        params = FuturesOrder(**params_dict)
        result = await self._client.futures.isolated.new_trade(params)
        await self._sleep()
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def get_open_orders(self) -> list[dict]:
        """Get unfilled limit orders."""
        result = await self._client.futures.isolated.get_open_trades()
        await self._sleep()
        return [t.model_dump() if hasattr(t, "model_dump") else t for t in result]

    async def cancel_order(self, trade_id: str) -> dict:
        """Cancel an unfilled limit order."""
        params = CancelTradeParams(id=trade_id)
        result = await self._client.futures.isolated.cancel(params)
        await self._sleep()
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def cancel_all_orders(self) -> None:
        """Cancel all unfilled limit orders."""
        await self._client.futures.isolated.cancel_all()
        await self._sleep()

    async def close_trade(self, trade_id: str) -> dict:
        """Close a specific isolated trade by ID."""
        from lnmarkets_sdk.v3.models.futures_isolated import CloseTradeParams

        params = CloseTradeParams(id=trade_id)
        result = await self._client.futures.isolated.close(params)
        await self._sleep()
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def update_stoploss(self, trade_id: str, value: float) -> dict:
        """Update stop-loss for a trade."""
        from lnmarkets_sdk.v3.models.futures_isolated import UpdateStoplossParams

        params = UpdateStoplossParams(id=trade_id, value=value)
        result = await self._client.futures.isolated.update_stoploss(params)
        await self._sleep()
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def update_takeprofit(self, trade_id: str, value: float) -> dict:
        """Update take-profit for a trade."""
        from lnmarkets_sdk.v3.models.futures_isolated import UpdateTakeprofitParams

        params = UpdateTakeprofitParams(id=trade_id, value=value)
        result = await self._client.futures.isolated.update_takeprofit(params)
        await self._sleep()
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def get_closed_trades(self, limit: int = 20) -> list[dict]:
        """Get recently closed trades."""
        params = GetClosedTradesParams(limit=limit)
        result = await self._client.futures.isolated.get_closed_trades(params)
        await self._sleep()
        data = result.data if hasattr(result, "data") else result
        return [t.model_dump() if hasattr(t, "model_dump") else t for t in data]

    async def get_funding_fees(self, limit: int = 20) -> list[dict]:
        """Get funding fees paid/received on isolated positions."""
        params = GetIsolatedFundingFeesParams(limit=limit)
        result = await self._client.futures.isolated.get_funding_fees(params)
        await self._sleep()
        data = result.data if hasattr(result, "data") else result
        return [f.model_dump() if hasattr(f, "model_dump") else f for f in data]
