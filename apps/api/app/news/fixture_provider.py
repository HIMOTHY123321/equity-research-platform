"""Deterministic fixture/mock NewsProvider (#A.1) -- the provider every test
in app.news/tests.unit.news uses. Takes a fixed, caller-supplied list of raw
article dicts at construction time and normalizes them once; querying never
re-normalizes or re-classifies, so results are byte-identical across calls
and across test runs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Union

from app.news.normalization import build_normalized_article
from app.news.provider import NewsProvider
from app.news.schemas import NormalizedNewsArticle


class FixtureNewsProvider(NewsProvider):
    def __init__(self, raw_articles: list[dict]) -> None:
        self._articles: list[NormalizedNewsArticle] = [
            build_normalized_article(
                provider="fixture",
                source=raw.get("source"),
                headline=raw["headline"],
                published_at=_as_utc(raw["published_at"]),
                received_at=_as_utc(raw["received_at"]) if raw.get("received_at") else None,
                url=raw.get("url"),
                raw_symbols=raw.get("symbols", []),
                raw_category=raw.get("raw_category"),
                provenance={"fixture": True},
                ingested_at=(
                    _as_utc(raw["ingested_at"]) if raw.get("ingested_at") else datetime.now(timezone.utc)
                ),
            )
            for raw in raw_articles
        ]

    def fetch_symbol_news(
        self, symbol: str, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]:
        symbol = symbol.upper()
        return [
            a
            for a in self._articles
            if symbol in a.symbols and start <= a.published_at <= end and a.published_at <= as_of
        ]

    def fetch_market_news(
        self, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]:
        return [a for a in self._articles if start <= a.published_at <= end and a.published_at <= as_of]


def _as_utc(value: Union[str, datetime]) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value
