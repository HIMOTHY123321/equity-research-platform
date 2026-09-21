"""Phase 12.1 (#L/#M): NewsMonitor -- provider-safe polling (yfinance has no
streaming news surface either), idempotent ingestion, and "NEW EVIDENCE
AVAILABLE" detection that never fires on a symbol's very first scan (that
would flag every pre-existing article as "new" the instant anyone
subscribes, which is not new evidence at all).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.live.news_monitor import NewsMonitor
from app.news.normalization import build_normalized_article
from app.news.provider import NewsProvider

_NOW = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)


class _MutableFixtureProvider(NewsProvider):
    """Unlike app.news.fixture_provider.FixtureNewsProvider (normalizes a
    fixed list once at construction), this lets a test append a genuinely
    new article between two scans -- exactly what proves the "new since
    last scan" detection actually works."""

    def __init__(self):
        self.articles = []

    def add(self, headline: str, published_at: datetime, symbols: list[str]) -> None:
        self.articles.append(
            build_normalized_article(
                provider="fixture",
                source="Reuters",
                headline=headline,
                published_at=published_at,
                received_at=None,
                url=None,
                raw_symbols=symbols,
                raw_category=None,
                provenance={"fixture": True},
                ingested_at=published_at,
            )
        )

    def fetch_symbol_news(self, symbol, start, end, as_of):
        symbol = symbol.upper()
        return [
            a
            for a in self.articles
            if symbol in a.symbols and start <= a.published_at <= end and a.published_at <= as_of
        ]

    def fetch_market_news(self, start, end, as_of):
        return [a for a in self.articles if start <= a.published_at <= end and a.published_at <= as_of]


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    return sessionmaker(bind=engine)


def test_first_scan_establishes_a_baseline_without_flagging_new_evidence():
    provider = _MutableFixtureProvider()
    provider.add("Acme reports earnings", _NOW, ["SPY"])
    monitor = NewsMonitor(_session_factory(), provider, now_fn=lambda: _NOW)
    monitor.subscribe("SPY")

    events = monitor.scan_once()
    assert events == []


def test_a_genuinely_new_article_on_a_later_scan_is_flagged():
    provider = _MutableFixtureProvider()
    provider.add("Acme reports earnings", _NOW, ["SPY"])
    monitor = NewsMonitor(_session_factory(), provider, now_fn=lambda: _NOW)
    monitor.subscribe("SPY")
    monitor.scan_once()  # baseline

    provider.add("Acme announces buyback", _NOW, ["SPY"])
    events = monitor.scan_once()

    assert len(events) == 1
    assert events[0].symbol == "SPY"
    assert events[0].new_article_count == 1


def test_no_change_between_scans_emits_nothing():
    provider = _MutableFixtureProvider()
    provider.add("Acme reports earnings", _NOW, ["SPY"])
    monitor = NewsMonitor(_session_factory(), provider, now_fn=lambda: _NOW)
    monitor.subscribe("SPY")
    monitor.scan_once()

    events = monitor.scan_once()
    assert events == []


def test_unsubscribe_removes_the_symbol_from_future_scans():
    provider = _MutableFixtureProvider()
    provider.add("Acme reports earnings", _NOW, ["SPY"])
    monitor = NewsMonitor(_session_factory(), provider, now_fn=lambda: _NOW)
    monitor.subscribe("SPY")
    monitor.scan_once()

    monitor.unsubscribe("SPY")
    provider.add("Acme announces buyback", _NOW, ["SPY"])
    events = monitor.scan_once()
    assert events == []


def test_one_symbols_provider_failure_does_not_abort_the_rest():
    class _FailingThenWorkingProvider(_MutableFixtureProvider):
        def fetch_symbol_news(self, symbol, start, end, as_of):
            if symbol == "BAD":
                raise RuntimeError("simulated provider outage")
            return super().fetch_symbol_news(symbol, start, end, as_of)

    provider = _FailingThenWorkingProvider()
    provider.add("Acme reports earnings", _NOW, ["SPY"])
    monitor = NewsMonitor(_session_factory(), provider, now_fn=lambda: _NOW)
    monitor.subscribe("BAD")
    monitor.subscribe("SPY")

    events = monitor.scan_once()  # must not raise
    assert events == []  # both are baseline scans


def test_listener_receives_the_new_evidence_event():
    provider = _MutableFixtureProvider()
    provider.add("Acme reports earnings", _NOW, ["SPY"])
    monitor = NewsMonitor(_session_factory(), provider, now_fn=lambda: _NOW)
    monitor.subscribe("SPY")
    monitor.scan_once()
    queue = monitor.add_listener()

    provider.add("Acme announces buyback", _NOW, ["SPY"])
    monitor.scan_once()

    event = queue.get_nowait()
    assert event.symbol == "SPY"
