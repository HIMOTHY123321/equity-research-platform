"""Phase 11.1 (#B/#C): the canonical point-in-time pipeline. Proves the
actual bug this phase fixes -- a historical `as_of` far enough back that a
live-sized candle fetch would leave nothing before it -- and that a
genuinely-unreachable `as_of` (past the provider's real retention) reports
insufficient/unavailable honestly rather than a silently-thin snapshot.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.ai_analysis.market_snapshot import _required_candle_count, build_market_snapshot
from app.api.routes.market import CANDLE_LIMIT_BY_TIMEFRAME
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1D, SPY_1H


class _DeepHistoryProvider(MarketDataProvider):
    """Returns the full fixture series regardless of requested limit (as a
    real provider with deep retention would) -- models "the provider
    genuinely has this much history," as opposed to a live-sized fetch
    that would truncate it away before the caller even sees it."""

    def get_candles(self, symbol, timeframe, limit=200):
        series = {Timeframe.ONE_HOUR: SPY_1H, Timeframe.ONE_DAY: SPY_1D, Timeframe.FOUR_HOUR: SPY_1H}.get(
            timeframe, []
        )
        return series[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


class _ShallowRetentionProvider(MarketDataProvider):
    """Only ever has the most recent `retained` candles, no matter how many
    are requested -- models a provider whose retention genuinely does not
    reach some historical `as_of` (e.g. yfinance intraday's ~60-day cap)."""

    def __init__(self, retained: int) -> None:
        self._retained = retained

    def get_candles(self, symbol, timeframe, limit=200):
        series = {Timeframe.ONE_HOUR: SPY_1H, Timeframe.ONE_DAY: SPY_1D, Timeframe.FOUR_HOUR: SPY_1H}.get(
            timeframe, []
        )
        return series[-min(limit, self._retained) :]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def test_required_candle_count_is_unchanged_for_live_as_of():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert _required_candle_count(Timeframe.ONE_HOUR, now, now, 2000) == 2000


def test_required_candle_count_grows_with_historical_age():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    as_of = now - timedelta(days=200)
    grown = _required_candle_count(Timeframe.ONE_HOUR, as_of, now, 2000)
    assert grown > 2000


def test_required_candle_count_is_capped():
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    as_of = now - timedelta(days=3650)
    assert _required_candle_count(Timeframe.FIVE_MIN, as_of, now, 12000) == 50_000


def test_historical_as_of_within_provider_reach_produces_a_real_snapshot():
    """The core bug proof: with the OLD fixed live-sized fetch, an as_of
    older than the live window would leave zero usable candles after
    truncation even though the provider (here, a deep-history fixture)
    genuinely has data that far back. The canonical pipeline must not
    silently return an empty/insufficient snapshot in that case."""
    as_of = SPY_1H[len(SPY_1H) // 2].timestamp
    now = SPY_1H[-1].timestamp
    snapshot = build_market_snapshot(
        "SPY", Timeframe.ONE_HOUR, _DeepHistoryProvider(), as_of, now=now
    )
    assert snapshot.setup_snapshot.data_quality.status.value == "ok"
    assert snapshot.market_data_cutoff is not None
    assert snapshot.market_data_cutoff <= as_of


def test_as_of_older_than_actual_provider_retention_reports_unavailable_not_partial():
    """A genuinely unreachable as_of (the provider's own retention doesn't
    go back that far) must surface through the engines' own existing
    insufficient/unavailable data_quality reporting -- never a fabricated
    partial snapshot."""
    now = SPY_1H[-1].timestamp
    retained = 50  # provider only ever has the most recent 50 bars
    as_of = SPY_1H[len(SPY_1H) // 2].timestamp  # comfortably before that window
    snapshot = build_market_snapshot(
        "SPY", Timeframe.ONE_HOUR, _ShallowRetentionProvider(retained), as_of, now=now
    )
    assert snapshot.setup_snapshot.data_quality.status.value == "unavailable"


def test_live_mode_candle_count_matches_pre_refactor_limit():
    now = SPY_1H[-1].timestamp
    snapshot = build_market_snapshot("SPY", Timeframe.ONE_HOUR, _DeepHistoryProvider(), now, now=now)
    limit = CANDLE_LIMIT_BY_TIMEFRAME[Timeframe.ONE_HOUR]
    assert snapshot.feature_snapshot.data_quality.candle_count <= limit
