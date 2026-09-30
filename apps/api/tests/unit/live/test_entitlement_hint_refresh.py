"""Phase 19.1 (§5/§6): LiveMarketService._refresh_entitlement_from_provider
-- the ONLY place a streaming provider's runtime-discovered entitlement
evidence (entitlement_hint()) is ever allowed to replace the service's
stored MarketDataEntitlement. Driven by a MockStreamingProvider subclass
that mimics TwelveDataStreamingProvider's evidence-based hint, never real
credentials or network access.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import pytest

from app.live.config import DEFAULT_LIVE_CONFIG
from app.live.entitlement import EntitlementStatus, MarketDataEntitlement
from app.live.mock_streaming import MockStreamingProvider
from app.live.service import LiveMarketService
from app.live.streaming import StreamTrade
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import PreviousClose

_BASE = datetime(2026, 6, 15, 13, 30, tzinfo=timezone.utc)


class _StubRestProvider(MarketDataProvider):
    def capabilities(self):
        from app.market_data.capabilities import ProviderCapabilities

        return ProviderCapabilities(
            real_time_quotes=False,
            streaming_quotes=False,
            streaming_trades=False,
            streaming_bars=False,
            streaming_news=False,
            historical_intraday=False,
            min_poll_interval_seconds=5.0,
        )

    def get_candles(self, symbol, timeframe, limit=200):
        return []

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        return PreviousClose(symbol=symbol, trading_date=_BASE.date(), close=100.0, volume=1_000_000)


class _EvidenceAwareStream(MockStreamingProvider):
    """Mimics TwelveDataStreamingProvider's evidence-based entitlement_hint
    without any real wire protocol -- the test drives it directly by
    setting `next_hint`."""

    def __init__(self) -> None:
        super().__init__()
        self.next_hint: Optional[MarketDataEntitlement] = None

    def entitlement_hint(self) -> Optional[MarketDataEntitlement]:
        return self.next_hint


def _fast_config():
    return DEFAULT_LIVE_CONFIG.__class__(
        reconnect_initial_backoff_seconds=0.01, reconnect_max_backoff_seconds=0.02
    )


async def _wait_until(predicate, timeout=2.0, step=0.01):
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return
        await asyncio.sleep(step)
        elapsed += step
    raise AssertionError("condition never became true")


@pytest.mark.asyncio
async def test_a_provider_with_no_opinion_never_changes_stored_entitlement():
    """Default StreamingMarketDataProvider.entitlement_hint() returns None
    -- Massive-shaped providers (MockStreamingProvider included) must leave
    LiveMarketService's constructor-supplied entitlement untouched."""
    rest = _StubRestProvider()
    stream = MockStreamingProvider()  # entitlement_hint() -> None, inherited default
    starting_entitlement = MarketDataEntitlement(
        provider="massive", status=EntitlementStatus.ENTITLED, reason="operator-confirmed"
    )
    service = LiveMarketService(
        rest,
        provider_name="massive",
        now_fn=lambda: _BASE,
        streaming_provider=stream,
        entitlement=starting_entitlement,
        config=_fast_config(),
    )
    await service.subscribe("SPY")
    await _wait_until(lambda: stream.connect_count >= 1)
    await asyncio.sleep(0.05)

    assert service.entitlement() == starting_entitlement
    await service.shutdown()


@pytest.mark.asyncio
async def test_genuine_subscription_evidence_upgrades_unknown_to_trial_only():
    rest = _StubRestProvider()
    stream = _EvidenceAwareStream()
    starting_entitlement = MarketDataEntitlement(
        provider="twelve_data", status=EntitlementStatus.UNKNOWN, reason="not yet discovered"
    )
    service = LiveMarketService(
        rest,
        provider_name="twelve_data",
        now_fn=lambda: _BASE,
        streaming_provider=stream,
        entitlement=starting_entitlement,
        config=_fast_config(),
    )
    stream.next_hint = MarketDataEntitlement(
        provider="twelve_data", status=EntitlementStatus.TRIAL_ONLY, reason="AAPL subscription confirmed"
    )

    await service.subscribe("AAPL")
    await _wait_until(lambda: service.entitlement().status == EntitlementStatus.TRIAL_ONLY)

    # Entitlement is confirmed, but no genuine tick has arrived yet.
    assert service.real_time_available() is False
    await service.shutdown()


@pytest.mark.asyncio
async def test_trial_only_becomes_real_time_available_only_after_a_genuine_tick():
    """Phase 19.1 (§6, live-validation finding): the exact false positive
    caught by testing against a real Twelve Data account -- an ACCEPTED
    subscription alone (TRIAL_ONLY) must never flip REAL TIME on by
    itself. Only once a genuine trade event has actually been ingested
    does real_time_available() become True."""
    rest = _StubRestProvider()
    stream = _EvidenceAwareStream()
    starting_entitlement = MarketDataEntitlement(
        provider="twelve_data", status=EntitlementStatus.UNKNOWN, reason="not yet discovered"
    )
    service = LiveMarketService(
        rest,
        provider_name="twelve_data",
        now_fn=lambda: _BASE,
        streaming_provider=stream,
        entitlement=starting_entitlement,
        config=_fast_config(),
    )
    stream.next_hint = MarketDataEntitlement(
        provider="twelve_data", status=EntitlementStatus.TRIAL_ONLY, reason="AAPL subscription confirmed"
    )

    await service.subscribe("AAPL")
    await _wait_until(lambda: service.entitlement().status == EntitlementStatus.TRIAL_ONLY)
    assert service.real_time_available() is False

    stream.push_event(
        StreamTrade(
            symbol="AAPL", price=123.45, size=0.0, exchange=None, conditions=(), source_timestamp=_BASE
        )
    )
    await _wait_until(lambda: service.latest_quote("AAPL") is not None)

    assert service.real_time_available() is True
    await service.shutdown()


@pytest.mark.asyncio
async def test_trial_only_real_time_available_goes_false_once_the_tick_goes_stale():
    """A single old tick with nothing since must not keep REAL TIME on
    forever -- freshness is evaluated against the CURRENT clock, not a
    snapshot taken when the tick first arrived."""
    rest = _StubRestProvider()
    stream = _EvidenceAwareStream()
    config = _fast_config()
    clock = {"now": _BASE}
    service = LiveMarketService(
        rest,
        provider_name="twelve_data",
        now_fn=lambda: clock["now"],
        streaming_provider=stream,
        entitlement=MarketDataEntitlement(
            provider="twelve_data", status=EntitlementStatus.TRIAL_ONLY, reason="AAPL subscription confirmed"
        ),
        config=config,
    )
    await service.subscribe("AAPL")
    await _wait_until(lambda: stream.connect_count >= 1)

    stream.push_event(
        StreamTrade(
            symbol="AAPL", price=123.45, size=0.0, exchange=None, conditions=(), source_timestamp=_BASE
        )
    )
    await _wait_until(lambda: service.latest_quote("AAPL") is not None)
    assert service.real_time_available() is True

    from datetime import timedelta

    clock["now"] = _BASE + timedelta(seconds=config.recent_max_age_seconds + 60)
    assert service.real_time_available() is False
    await service.shutdown()


@pytest.mark.asyncio
async def test_rejected_symbol_evidence_never_lets_real_time_available_become_true():
    rest = _StubRestProvider()
    stream = _EvidenceAwareStream()
    starting_entitlement = MarketDataEntitlement(
        provider="twelve_data", status=EntitlementStatus.UNKNOWN, reason="not yet discovered"
    )
    service = LiveMarketService(
        rest,
        provider_name="twelve_data",
        now_fn=lambda: _BASE,
        streaming_provider=stream,
        entitlement=starting_entitlement,
        config=_fast_config(),
    )
    stream.next_hint = MarketDataEntitlement(
        provider="twelve_data", status=EntitlementStatus.NOT_ENTITLED, reason="ZZZZZ rejected"
    )

    await service.subscribe("ZZZZZ")
    await _wait_until(lambda: service.entitlement().status == EntitlementStatus.NOT_ENTITLED)

    assert service.real_time_available() is False
    await service.shutdown()


@pytest.mark.asyncio
async def test_streaming_diagnostics_reports_provider_evidence():
    rest = _StubRestProvider()
    stream = _EvidenceAwareStream()
    stream.subscribed_symbols = {"AAPL"}
    stream.rejected_symbols = {"ZZZZZ"}
    service = LiveMarketService(rest, provider_name="twelve_data", streaming_provider=stream)

    diagnostics = service.streaming_diagnostics()
    assert diagnostics == {"subscribed_symbols": ["AAPL"], "rejected_symbols": ["ZZZZZ"]}


def test_streaming_diagnostics_is_none_without_a_streaming_provider():
    rest = _StubRestProvider()
    service = LiveMarketService(rest, provider_name="yfinance")
    assert service.streaming_diagnostics() is None
