"""Real-candle-fixture MarketSnapshot factory for decision_engine tests --
same convention as tests/unit/ai_analysis/conftest.py: build genuinely
realistic snapshots via the real `build_market_snapshot` pipeline rather
than hand-instantiating the nested pydantic models (which would risk
drifting from the real schemas)."""

from __future__ import annotations

from datetime import timedelta

from app.ai_analysis.market_snapshot import MarketSnapshot, build_market_snapshot
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1H, FakeMarketDataProvider


def spy_snapshot(*, timeframe: Timeframe = Timeframe.ONE_HOUR, as_of=None) -> MarketSnapshot:
    provider = FakeMarketDataProvider()
    resolved_as_of = as_of or (SPY_1H[-1].timestamp + timedelta(hours=1))
    return build_market_snapshot("SPY", timeframe, provider, resolved_as_of, now=resolved_as_of)


def spy_snapshot_at_index(index: int, *, timeframe: Timeframe = Timeframe.ONE_HOUR) -> MarketSnapshot:
    """A snapshot as of just after SPY_1H[index] closes -- lets tests build
    two snapshots at different points in the same real history to exercise
    evidence-diff/state-transition behavior deterministically."""
    as_of = SPY_1H[index].timestamp + timedelta(minutes=1)
    return spy_snapshot(timeframe=timeframe, as_of=as_of)
