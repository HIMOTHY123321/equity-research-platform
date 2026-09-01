"""yfinance news metadata -- a DEVELOPMENT/RESEARCH ONLY NewsProvider (#A.2,
#O). No brokerage account or API key required (same access model as
app.market_data.yfinance_provider).

IMPORTANT LICENSING LIMITATION (#O), stated plainly: this wraps
`yfinance.Ticker.news`, an unofficial interface into Yahoo Finance's own
news aggregation, intended for local development and research only -- not
a licensed, redistributable, commercial news feed. A commercial product
needs a properly licensed news/data provider (e.g. a licensed newswire or
market-data vendor with a news product). Swapping one in means writing one
more class satisfying `NewsProvider`, the same one-interface-per-vendor
pattern app.market_data.provider already established; nothing downstream of
the provider boundary needs to change. No yfinance-specific field name or
structure appears anywhere outside this file.

IMPORTANT DATA LIMITATION: yfinance's news endpoint returns whatever Yahoo
currently has cached as "recent news" for a ticker -- it is NOT a queryable
historical archive; there is no `start=`/`end=` parameter Yahoo honors here.
This provider can only ever return what Yahoo happens to have right now,
filtered client-side to the caller's requested window, and cannot backfill
news from an arbitrary past date range. Historical catalyst research in this
phase runs against `FixtureNewsProvider`'s deterministic fixture data, not
against this provider, for exactly this reason (see ADR 0013).

Verified live against real AAPL data (2026-08-31): `Ticker.news` returns a
list of `{"id": ..., "content": {...}}` items; `content.title`, `content
.pubDate` (ISO-8601, "Z"-suffixed UTC), `content.provider.displayName`,
`content.canonicalUrl.url`, and `content.contentType` are the fields read
below. Every field is read defensively (`.get`, never attribute access) and
a malformed/missing-field article is skipped with a warning, never allowed
to crash ingestion of the rest of the batch (#B "be explicit when fields
are missing, never fabricate") -- this shape is not contractually
guaranteed stable by Yahoo/yfinance across versions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import yfinance as yf

from app.news.normalization import build_normalized_article
from app.news.provider import NewsProvider
from app.news.schemas import NormalizedNewsArticle

logger = logging.getLogger(__name__)


class YFinanceNewsProvider(NewsProvider):
    """DEVELOPMENT / RESEARCH ONLY -- see module docstring."""

    def __init__(
        self,
        ticker_factory: Callable[[str], Any] = yf.Ticker,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._ticker_factory = ticker_factory
        self._now = now_fn

    def fetch_symbol_news(
        self, symbol: str, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]:
        raw_items = self._raw_news(symbol)
        articles = [a for a in (self._normalize_one(item, [symbol]) for item in raw_items) if a is not None]
        return [a for a in articles if start <= a.published_at <= end and a.published_at <= as_of]

    def fetch_market_news(
        self, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]:
        # yfinance exposes no market-wide news endpoint distinct from a
        # per-ticker one -- a caller wanting a cross-symbol view is expected
        # to aggregate fetch_symbol_news across a watchlist/universe instead
        # (see app/api/routes/news.py's "what's moving" aggregation).
        # Documented as a real limitation, not silently faked.
        return []

    def _raw_news(self, symbol: str) -> list[dict]:
        try:
            ticker = self._ticker_factory(symbol)
            items = ticker.news
            return items if isinstance(items, list) else []
        except Exception as exc:  # yfinance doesn't expose a narrower type here
            logger.warning("Failed to fetch yfinance news for %s: %s", symbol, exc)
            return []

    def _normalize_one(self, item: dict, requested_symbols: list[str]) -> Optional[NormalizedNewsArticle]:
        try:
            content = item.get("content") if isinstance(item.get("content"), dict) else item

            headline = content.get("title") or content.get("headline")
            if not headline:
                return None

            published_raw = (
                content.get("pubDate")
                or content.get("providerPublishTime")
                or item.get("providerPublishTime")
            )
            published_at = _parse_timestamp(published_raw)
            if published_at is None:
                return None

            provider_block = content.get("provider") if isinstance(content.get("provider"), dict) else {}
            source = provider_block.get("displayName") or content.get("publisher")

            url_block = content.get("canonicalUrl") if isinstance(content.get("canonicalUrl"), dict) else {}
            url = url_block.get("url") or content.get("link")

            raw_category = content.get("contentType")

            return build_normalized_article(
                provider="yfinance",
                source=source,
                headline=headline,
                published_at=published_at,
                url=url,
                raw_symbols=requested_symbols,
                raw_category=raw_category,
                provenance={"yfinance_raw_keys": sorted(item.keys())},
                ingested_at=self._now(),
            )
        except Exception as exc:  # never let one malformed article break the batch
            logger.warning("Skipping malformed yfinance news item: %s", exc)
            return None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None
