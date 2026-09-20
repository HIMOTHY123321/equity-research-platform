"""Phase 12 (#N): the forecasting pipeline must never hardcode logic for
any specific symbol (including newly-listed ones) -- readiness for a
newly-public ticker is a property of the *generic* pipeline honestly
reporting what it has, not a special case. These tests exercise that
genericity directly: one arbitrary placeholder symbol with only a handful
of candles (simulating a stock a few days post-IPO), and a provider that
raises for a ticker it has never heard of. Neither may crash, and neither
may fabricate a longer history than actually exists.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.forecasting.repository import SqlAlchemyForecastRepository
from app.forecasting.resolver import resolve_forecast
from app.forecasting.schemas import ForecastCategory, ForecastStatus
from app.forecasting.service import create_forecast
from app.market_data.exceptions import InvalidSymbolError
from app.market_data.provider import MarketDataProvider
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Candle, MarketSession, Timeframe
from tests.unit.ai_analysis.conftest import make_session
from tests.unit.forecasting.conftest import seeded_repositories

_BASE = datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc)


def _tiny_history_candles(count: int) -> list[Candle]:
    """A handful of hourly bars -- roughly what a stock has a few trading
    days after an IPO, deliberately not a realistic multi-month fixture."""
    candles = []
    price = 50.0
    for i in range(count):
        candles.append(
            Candle(
                symbol="NEWCO",
                timeframe=Timeframe.ONE_HOUR,
                timestamp=_BASE + timedelta(hours=i),
                session=MarketSession.REGULAR,
                open=price,
                high=price + 1,
                low=price - 1,
                close=price + 0.5,
                volume=100_000,
            )
        )
        price += 0.3
    return candles


class NewlyListedProvider(MarketDataProvider):
    """Recognizes exactly one symbol, with a short listing history --
    unlike FakeMarketDataProvider elsewhere, any other symbol raises,
    modeling a provider that has genuinely never heard of the ticker."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    def get_candles(self, symbol, timeframe, limit=200):
        if symbol != "NEWCO":
            raise InvalidSymbolError(symbol)
        return self._candles if timeframe == Timeframe.ONE_HOUR else []

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def _repos():
    session = make_session()
    research_repository, news_repository = seeded_repositories()
    evidence_repository = SqlAlchemyEvidenceRepository(session)
    forecast_repository = SqlAlchemyForecastRepository(session)
    return research_repository, news_repository, evidence_repository, forecast_repository


def test_provider_unknown_ticker_raises_cleanly_not_a_crash():
    provider = NewlyListedProvider(_tiny_history_candles(8))
    research_repository, news_repository, evidence_repository, forecast_repository = _repos()

    with pytest.raises(InvalidSymbolError):
        create_forecast(
            symbol="DOES-NOT-EXIST",
            timeframe=Timeframe.ONE_HOUR,
            forecast_category=ForecastCategory.VOLATILITY,
            horizon_bars=5,
            market_provider=provider,
            news_provider=FixtureNewsProvider([]),
            news_repository=news_repository,
            research_repository=research_repository,
            evidence_repository=evidence_repository,
            forecast_repository=forecast_repository,
            market_as_of=_BASE,
        )


def test_newly_listed_symbol_with_limited_history_abstains_honestly_not_a_crash():
    candles = _tiny_history_candles(8)
    provider = NewlyListedProvider(candles)
    research_repository, news_repository, evidence_repository, forecast_repository = _repos()

    forecast = create_forecast(
        symbol="NEWCO",
        timeframe=Timeframe.ONE_HOUR,
        forecast_category=ForecastCategory.VOLATILITY,
        horizon_bars=5,
        market_provider=provider,
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        evidence_repository=evidence_repository,
        forecast_repository=forecast_repository,
        market_as_of=candles[-1].timestamp,
    )
    assert forecast.status == ForecastStatus.ABSTAINED
    assert forecast.forecast_value is None
    # Honest about *why* -- not a generic catch-all, and never a fabricated
    # long-history sample masquerading as real evidence.
    assert forecast.abstention_reason is not None


def test_newly_listed_symbol_direction_forecast_also_abstains_without_setup():
    candles = _tiny_history_candles(8)
    provider = NewlyListedProvider(candles)
    research_repository, news_repository, evidence_repository, forecast_repository = _repos()

    forecast = create_forecast(
        symbol="NEWCO",
        timeframe=Timeframe.ONE_HOUR,
        forecast_category=ForecastCategory.DIRECTION,
        horizon_bars=5,
        market_provider=provider,
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        evidence_repository=evidence_repository,
        forecast_repository=forecast_repository,
        market_as_of=candles[-1].timestamp,
    )
    assert forecast.status == ForecastStatus.ABSTAINED


def test_resolving_a_newly_listed_symbol_forecast_reports_insufficient_future_data_honestly():
    candles = _tiny_history_candles(8)
    provider = NewlyListedProvider(candles)
    research_repository, news_repository, evidence_repository, forecast_repository = _repos()

    forecast = create_forecast(
        symbol="NEWCO",
        timeframe=Timeframe.ONE_HOUR,
        forecast_category=ForecastCategory.VOLATILITY,
        horizon_bars=5,
        market_provider=provider,
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        evidence_repository=evidence_repository,
        forecast_repository=forecast_repository,
        market_as_of=candles[3].timestamp,  # leaves only 4 future candles, fewer than most horizons
    )
    # This particular forecast abstained (no candles for a real volatility
    # read at all), so resolution should say so rather than crash.
    outcome = resolve_forecast(forecast, provider, evidence_repository)
    assert outcome.outcome.value == "insufficient_future_data"
