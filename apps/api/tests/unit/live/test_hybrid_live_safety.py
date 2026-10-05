"""Phase 19.2: proves the exact safety property the hybrid provider must
never violate -- a REST quote (whether served by Twelve Data or a
yfinance fallback) can never, by itself, make real_time_available() True.
Only a genuine WebSocket tick can. Uses HybridMarketDataProvider as the
REST provider and MockStreamingProvider as the streaming provider, never
real network access."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.live.config import DEFAULT_LIVE_CONFIG
from app.live.entitlement import EntitlementStatus, MarketDataEntitlement
from app.live.mock_streaming import MockStreamingProvider
from app.live.service import LiveMarketService
from app.live.streaming import StreamTrade
from app.market_data.exceptions import RateLimitError
from app.market_data.hybrid_provider import HybridMarketDataProvider
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import MarketSession, PreviousClose, Quote

_BASE = datetime(2026, 6, 15, 13, 30, tzinfo=timezone.utc)


class _StubRest(MarketDataProvider):
    """A plain REST provider with a fully fresh quote always available --
    used as either the "primary" or "historical" half of a hybrid, so a
    test can prove that even a maximally-fresh REST quote never reaches
    real_time_available()."""

    def __init__(self, name: str, fail: bool = False):
        self.name = name
        self.fail = fail

    def get_candles(self, symbol, timeframe, limit=200, before=None):
        return []

    def get_latest_quote(self, symbol):
        if self.fail:
            raise RateLimitError("429")
        return Quote(
            symbol=symbol,
            timestamp=_BASE,
            session=MarketSession.REGULAR,
            bid_price=100.0,
            bid_size=1.0,
            ask_price=100.1,
            ask_size=1.0,
            is_approximate=True,
        )

    def get_previous_close(self, symbol):
        return PreviousClose(symbol=symbol, trading_date=_BASE.date(), close=99.0, volume=1_000_000)


class _EvidenceAwareStream(MockStreamingProvider):
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
async def test_fresh_rest_quote_through_a_fallback_hybrid_provider_cannot_satisfy_real_time():
    """Twelve Data (the primary) is forced to fail, so the hybrid provider
    serves a 'now'-fresh yfinance fallback quote with clock.now() == the
    quote's own timestamp (maximally fresh). Even so, as long as the
    LiveMarketService is configured for streaming, this quote is never
    polled into last_live_quote at all (see _use_streaming()'s poll-loop
    gating) and could not satisfy _has_fresh_live_data() even if it were."""
    hybrid = HybridMarketDataProvider(
        primary=_StubRest("twelve_data", fail=True), historical=_StubRest("yfinance")
    )
    stream = _EvidenceAwareStream()
    service = LiveMarketService(
        hybrid,
        provider_name="hybrid",
        now_fn=lambda: _BASE,
        streaming_provider=stream,
        entitlement=MarketDataEntitlement(
            provider="hybrid", status=EntitlementStatus.UNKNOWN, reason="not yet discovered"
        ),
        config=_fast_config(),
    )
    stream.next_hint = MarketDataEntitlement(
        provider="hybrid", status=EntitlementStatus.TRIAL_ONLY, reason="AAPL subscription confirmed"
    )

    await service.subscribe("AAPL")
    await _wait_until(lambda: service.entitlement().status == EntitlementStatus.TRIAL_ONLY)

    # A maximally-fresh REST quote exists (hybrid.get_latest_quote would
    # return one right now), and entitlement is TRIAL_ONLY -- yet without a
    # genuine WS tick, REAL TIME must stay False.
    assert service.real_time_available() is False
    await service.shutdown()


@pytest.mark.asyncio
async def test_direct_rest_ingestion_cannot_satisfy_the_freshness_gate_even_if_called():
    """Defense in depth: even if something were to call ingest_quote (the
    REST path) directly while streaming is configured -- which nothing in
    this codebase does while _use_streaming() is True -- a REST-sourced
    quote must still never satisfy _has_fresh_live_data(), because that
    check reads _SymbolState.last_stream_quote, which only genuine
    ingest_trade/ingest_nbbo calls ever populate."""
    hybrid = HybridMarketDataProvider(primary=_StubRest("twelve_data"), historical=_StubRest("yfinance"))
    stream = _EvidenceAwareStream()
    service = LiveMarketService(
        hybrid,
        provider_name="hybrid",
        now_fn=lambda: _BASE,
        streaming_provider=stream,
        entitlement=MarketDataEntitlement(
            provider="hybrid", status=EntitlementStatus.TRIAL_ONLY, reason="AAPL subscription confirmed"
        ),
        config=_fast_config(),
    )
    await service.subscribe("AAPL")
    await _wait_until(lambda: stream.connect_count >= 1)

    fresh_quote = hybrid.get_latest_quote("AAPL")
    assert fresh_quote.provider == "twelve_data"
    service.ingest_quote("AAPL", fresh_quote, received_at=_BASE)

    # The REST quote is now the displayed quote...
    assert service.latest_quote("AAPL") is not None
    # ...but it still must not satisfy REAL TIME.
    assert service.real_time_available() is False
    await service.shutdown()


@pytest.mark.asyncio
async def test_genuine_ws_tick_still_satisfies_real_time_after_the_hardening():
    """Regression guard: the Phase 19.2 last_stream_quote hardening must
    not break the Phase 19.1 happy path -- a genuine trade tick still
    makes real_time_available() True."""
    hybrid = HybridMarketDataProvider(primary=_StubRest("twelve_data"), historical=_StubRest("yfinance"))
    stream = _EvidenceAwareStream()
    service = LiveMarketService(
        hybrid,
        provider_name="hybrid",
        now_fn=lambda: _BASE,
        streaming_provider=stream,
        entitlement=MarketDataEntitlement(
            provider="hybrid", status=EntitlementStatus.TRIAL_ONLY, reason="AAPL subscription confirmed"
        ),
        config=_fast_config(),
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
    await service.shutdown()


@pytest.mark.asyncio
async def test_stale_ws_tick_plus_fresh_rest_quote_still_does_not_show_real_time():
    """The exact scenario named in the Phase 19.2 spec: an old WS tick (now
    stale) plus a brand-new, maximally-fresh REST quote must still not
    show REAL TIME -- REST freshness is never a substitute for a genuine,
    still-fresh stream tick."""
    hybrid = HybridMarketDataProvider(primary=_StubRest("twelve_data"), historical=_StubRest("yfinance"))
    stream = _EvidenceAwareStream()
    config = _fast_config()
    clock = {"now": _BASE}
    service = LiveMarketService(
        hybrid,
        provider_name="hybrid",
        now_fn=lambda: clock["now"],
        streaming_provider=stream,
        entitlement=MarketDataEntitlement(
            provider="hybrid", status=EntitlementStatus.TRIAL_ONLY, reason="AAPL subscription confirmed"
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

    # Time passes well beyond the freshness window -- the WS tick goes stale.
    stale_now = _BASE + timedelta(seconds=config.recent_max_age_seconds + 60)
    clock["now"] = stale_now
    assert service.real_time_available() is False

    # A brand-new REST quote arrives, timestamped at the current (stale_now) instant.
    fresh_rest_quote = Quote(
        symbol="AAPL",
        timestamp=stale_now,
        session=MarketSession.REGULAR,
        bid_price=130.0,
        bid_size=1.0,
        ask_price=130.1,
        ask_size=1.0,
        is_approximate=True,
        provider="yfinance",
    )
    service.ingest_quote("AAPL", fresh_rest_quote, received_at=stale_now)

    assert service.latest_quote("AAPL").bid == 130.0  # the display quote did update
    assert service.real_time_available() is False  # but REAL TIME still correctly stays False
    await service.shutdown()


@pytest.mark.asyncio
async def test_provider_label_switch_between_consecutive_quotes_does_not_duplicate_events():
    """'Provider switching does not duplicate events' at the lowest common
    mechanism every downstream consumer (decisions/alerts/prospective
    observations) relies on: LiveMarketService's own timestamp-monotonic
    dedup in ingest_quote, which is keyed on the quote's timestamp, never
    on which provider served it. A second quote at the SAME source
    timestamp -- even if its provenance label changed from twelve_data to
    yfinance (a mid-session fallback) -- must still be dropped as a
    duplicate, not treated as a new tick."""
    hybrid = HybridMarketDataProvider(primary=_StubRest("twelve_data"), historical=_StubRest("yfinance"))
    service = LiveMarketService(hybrid, provider_name="hybrid", now_fn=lambda: _BASE)
    events: list = []
    queue = service.add_listener()

    quote_a = Quote(
        symbol="AAPL",
        timestamp=_BASE,
        session=MarketSession.REGULAR,
        bid_price=100.0,
        bid_size=1.0,
        ask_price=100.1,
        ask_size=1.0,
        provider="twelve_data",
    )
    quote_b = Quote(
        symbol="AAPL",
        timestamp=_BASE,  # identical source timestamp -- a provider fallback, not a new tick
        session=MarketSession.REGULAR,
        bid_price=999.0,
        bid_size=1.0,
        ask_price=999.1,
        ask_size=1.0,
        provider="yfinance",
    )

    service.ingest_quote("AAPL", quote_a, received_at=_BASE)
    service.ingest_quote("AAPL", quote_b, received_at=_BASE)

    while not queue.empty():
        events.append(queue.get_nowait())

    quote_events = [e for e in events if type(e).__name__ == "QuoteEvent"]
    assert len(quote_events) == 1
    assert service.latest_quote("AAPL").bid == 100.0
