"""
Funding rate analysis and trade decision logic.

Core idea: When funding rate is significantly positive, shorts get paid.
When significantly negative, longs get paid. We position accordingly
and collect funding payments as income.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import config

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Represents a trading decision."""

    action: str  # "open_short", "open_long", "close", "hold"
    reason: str
    funding_rate: float
    confidence: float  # 0.0 to 1.0
    suggested_leverage: int = config.MAX_LEVERAGE
    suggested_margin: int = config.MARGIN_PER_TRADE


@dataclass
class FundingAnalysis:
    """Result of funding rate analysis."""

    current_rate: float
    avg_rate: float
    trend: str  # "positive", "negative", "neutral"
    consecutive_same_sign: int
    is_strong_signal: bool


def analyze_funding(settlements: list[dict]) -> FundingAnalysis:
    """
    Analyze recent funding settlements to determine trend and strength.

    Args:
        settlements: List of funding settlement dicts, most recent first.
                     Each should have 'funding_rate' key.
    """
    if not settlements:
        return FundingAnalysis(
            current_rate=0.0,
            avg_rate=0.0,
            trend="neutral",
            consecutive_same_sign=0,
            is_strong_signal=False,
        )

    rates = [s.get("funding_rate", 0.0) for s in settlements]
    current_rate = rates[0]
    avg_rate = sum(rates) / len(rates)

    # Count consecutive same-sign settlements
    consecutive = 1
    if len(rates) > 1:
        sign = 1 if rates[0] > 0 else -1
        for rate in rates[1:]:
            if (rate > 0 and sign > 0) or (rate < 0 and sign < 0):
                consecutive += 1
            else:
                break

    # Determine trend
    if avg_rate > config.FUNDING_RATE_THRESHOLD:
        trend = "positive"
    elif avg_rate < -config.FUNDING_RATE_THRESHOLD:
        trend = "negative"
    else:
        trend = "neutral"

    is_strong = (
        abs(current_rate) > config.FUNDING_RATE_THRESHOLD
        and consecutive >= config.MIN_CONSECUTIVE_SAME_SIGN
    )

    analysis = FundingAnalysis(
        current_rate=current_rate,
        avg_rate=avg_rate,
        trend=trend,
        consecutive_same_sign=consecutive,
        is_strong_signal=is_strong,
    )

    logger.info(
        "Funding analysis: rate=%.4f%% avg=%.4f%% trend=%s consecutive=%d strong=%s",
        current_rate,
        avg_rate,
        trend,
        consecutive,
        is_strong,
    )

    return analysis


def decide_action(
    analysis: FundingAnalysis,
    current_positions: list[dict],
    daily_pnl_sats: int,
) -> TradeSignal:
    """
    Decide what to do based on funding analysis and current state.

    Logic:
    - If funding is strongly positive → short (we get paid funding)
    - If funding is strongly negative → long (we get paid funding)
    - If we have a position opposite to the current funding trend → close it
    - If signal is weak or we're at risk limits → hold

    Args:
        analysis: Result of analyze_funding()
        current_positions: Currently open trades
        daily_pnl_sats: Today's realized P&L in sats
    """

    # Check daily loss limit
    if daily_pnl_sats <= -config.DAILY_LOSS_LIMIT_SATS:
        return TradeSignal(
            action="hold",
            reason=f"Daily loss limit reached ({daily_pnl_sats} sats)",
            funding_rate=analysis.current_rate,
            confidence=1.0,
        )

    # Check position limit
    if len(current_positions) >= config.MAX_OPEN_POSITIONS:
        # Check if any existing position is against the trend
        signal = _check_for_close(analysis, current_positions)
        if signal:
            return signal

        return TradeSignal(
            action="hold",
            reason=f"Max positions reached ({len(current_positions)}/{config.MAX_OPEN_POSITIONS})",
            funding_rate=analysis.current_rate,
            confidence=0.5,
        )

    # Check if we should close any existing positions first
    close_signal = _check_for_close(analysis, current_positions)
    if close_signal:
        return close_signal

    # Check for entry signals
    if not analysis.is_strong_signal:
        return TradeSignal(
            action="hold",
            reason=f"Weak signal: rate={analysis.current_rate:.4f}%, consecutive={analysis.consecutive_same_sign}",
            funding_rate=analysis.current_rate,
            confidence=0.2,
        )

    # Strong positive funding → short to collect
    if analysis.trend == "positive" and analysis.current_rate > 0:
        # Check we don't already have a short
        has_short = any(
            p.get("side") in ("sell", "s") for p in current_positions
        )
        if has_short:
            return TradeSignal(
                action="hold",
                reason="Already have a short position collecting funding",
                funding_rate=analysis.current_rate,
                confidence=0.3,
            )

        confidence = min(1.0, analysis.consecutive_same_sign / 6.0)
        return TradeSignal(
            action="open_short",
            reason=f"Positive funding ({analysis.current_rate:.4f}%), {analysis.consecutive_same_sign} consecutive — shorting to collect",
            funding_rate=analysis.current_rate,
            confidence=confidence,
        )

    # Strong negative funding → long to collect
    if analysis.trend == "negative" and analysis.current_rate < 0:
        has_long = any(
            p.get("side") in ("buy", "b") for p in current_positions
        )
        if has_long:
            return TradeSignal(
                action="hold",
                reason="Already have a long position collecting funding",
                funding_rate=analysis.current_rate,
                confidence=0.3,
            )

        confidence = min(1.0, analysis.consecutive_same_sign / 6.0)
        return TradeSignal(
            action="open_long",
            reason=f"Negative funding ({analysis.current_rate:.4f}%), {analysis.consecutive_same_sign} consecutive — longing to collect",
            funding_rate=analysis.current_rate,
            confidence=confidence,
        )

    return TradeSignal(
        action="hold",
        reason="No clear funding opportunity",
        funding_rate=analysis.current_rate,
        confidence=0.1,
    )


def _check_for_close(
    analysis: FundingAnalysis,
    positions: list[dict],
) -> Optional[TradeSignal]:
    """Check if any position should be closed due to funding flip."""
    for pos in positions:
        side = pos.get("side", "")
        is_long = side in ("buy", "b")
        is_short = side in ("sell", "s")

        # Close long if funding flipped positive (longs now pay)
        if is_long and analysis.trend == "positive" and analysis.is_strong_signal:
            return TradeSignal(
                action="close",
                reason=f"Funding flipped positive ({analysis.current_rate:.4f}%) — closing long to stop paying",
                funding_rate=analysis.current_rate,
                confidence=0.8,
            )

        # Close short if funding flipped negative (shorts now pay)
        if is_short and analysis.trend == "negative" and analysis.is_strong_signal:
            return TradeSignal(
                action="close",
                reason=f"Funding flipped negative ({analysis.current_rate:.4f}%) — closing short to stop paying",
                funding_rate=analysis.current_rate,
                confidence=0.8,
            )

    return None


def calculate_stop_take(
    side: str,
    entry_price: float,
) -> tuple[float, float]:
    """
    Calculate stop-loss and take-profit prices.

    Args:
        side: "buy" or "sell"
        entry_price: entry price

    Returns:
        (stoploss_price, takeprofit_price)
    """
    sl_pct = config.STOP_LOSS_PCT / 100.0
    tp_pct = config.TAKE_PROFIT_PCT / 100.0

    if side == "buy":
        stoploss = entry_price * (1 - sl_pct)
        takeprofit = entry_price * (1 + tp_pct)
    else:  # sell/short
        stoploss = entry_price * (1 + sl_pct)
        takeprofit = entry_price * (1 - tp_pct)

    return round(stoploss, 2), round(takeprofit, 2)
