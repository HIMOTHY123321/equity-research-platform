"""Shared fixture builders for Long-Term Research tests -- deterministic,
no network, no randomness."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.long_term_research.schemas import FundamentalsSnapshot
from app.schemas.market_data import Candle, MarketSession, Timeframe


def make_daily_candles(
    as_of: datetime, *, days: int, start_price: float, daily_multiplier: float
) -> list[Candle]:
    candles: list[Candle] = []
    price = start_price
    for i in range(days):
        ts = as_of - timedelta(days=days - i)
        price *= daily_multiplier
        candles.append(
            Candle(
                symbol="TEST",
                timeframe=Timeframe.ONE_DAY,
                timestamp=ts,
                session=MarketSession.REGULAR,
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1_000_000,
            )
        )
    return candles


def strong_positive_fundamentals(as_of: datetime, *, symbol: str = "TEST") -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        symbol=symbol,
        fetched_at=as_of,
        provider="fixture",
        trailing_pe=18.0,
        profit_margin=0.22,
        return_on_equity=0.20,
        debt_to_equity=40.0,
        free_cash_flow=500.0,
        quarterly_revenue=[100, 110, 121, 133, 146, 161, 177, 195],
        quarterly_eps=[1.0, 1.1, 1.21, 1.33, 1.46, 1.61, 1.77, 1.95],
    )


def weak_negative_fundamentals(as_of: datetime, *, symbol: str = "TEST") -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        symbol=symbol,
        fetched_at=as_of,
        provider="fixture",
        trailing_pe=45.0,
        profit_margin=-0.05,
        return_on_equity=-0.10,
        debt_to_equity=250.0,
        free_cash_flow=-50.0,
        quarterly_revenue=[195, 177, 161, 146, 133, 121, 110, 100],
        quarterly_eps=[1.95, 1.77, 1.61, 1.46, 1.33, 1.21, 1.1, 1.0],
    )


def strong_positive_candles(as_of: datetime) -> list[Candle]:
    """Nearly-flat price with strongly growing EPS (see
    strong_positive_fundamentals) -- drives valuation to CHEAP via the
    own-history P/E comparison, and the price stack to CONSTRUCTIVE."""
    return make_daily_candles(as_of, days=400, start_price=100.0, daily_multiplier=1.0005)


def weak_negative_candles(as_of: datetime) -> list[Candle]:
    return make_daily_candles(as_of, days=400, start_price=100.0, daily_multiplier=0.998)
