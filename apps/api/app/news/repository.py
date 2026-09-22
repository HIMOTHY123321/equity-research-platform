"""Persistence for the News/Catalyst Context engine (#L). Same
ABC + SqlAlchemy-impl + local-SQLite-bootstrap-via-`create_all` convention as
`app.research.repository` / `app.research_intelligence.snapshots` /
`app.market_data.candle_cache`.

Design note on as_of correctness (#E), consistent with app.news.events'
module docstring: `events_for_symbol_as_of` NEVER reads the persisted
`catalyst_events` table directly -- it re-derives events fresh from
`get_articles_for_symbol` (itself filtered to `published_at <= as_of`) via
`group_into_events`, every single call. This is what guarantees a historical
as_of query is unaffected by articles ingested later, regardless of what the
persisted "current" snapshot table looks like at query time.
`list_recent_events`, by contrast, reads the persisted table directly and is
explicitly NOT as_of-safe -- it is only for the "what's moving right now"
dashboard view, documented as such below.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    Base,
    CatalystEventArticleRecord,
    CatalystEventRecord,
    CatalystReactionRecord,
    NewsArticleRecord,
)
from app.news.config import DEFAULT_CATALYST_CONFIG, CatalystConfig
from app.news.events import group_into_events
from app.news.schemas import CatalystEvent, MarketReaction, NormalizedNewsArticle


class NewsRepository(ABC):
    @abstractmethod
    def upsert_articles(self, articles: list[NormalizedNewsArticle]) -> int: ...

    @abstractmethod
    def get_articles_for_symbol(
        self, symbol: str, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]: ...

    @abstractmethod
    def get_market_articles(
        self, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]: ...

    @abstractmethod
    def events_for_symbol_as_of(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        config: CatalystConfig = DEFAULT_CATALYST_CONFIG,
    ) -> list[CatalystEvent]: ...

    @abstractmethod
    def persist_events_snapshot(self, events: list[CatalystEvent]) -> None: ...

    @abstractmethod
    def list_recent_events(self, *, limit: int = 50) -> list[CatalystEvent]: ...

    @abstractmethod
    def get_event_by_id(self, event_id: str) -> Optional[CatalystEvent]: ...

    @abstractmethod
    def get_articles_by_ids(self, article_ids: list[str]) -> list[NormalizedNewsArticle]: ...

    @abstractmethod
    def upsert_reaction(self, reaction: MarketReaction) -> None: ...

    @abstractmethod
    def get_reaction(self, event_id: str, symbol: str, timeframe: str) -> Optional[MarketReaction]: ...


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite has no native timezone-aware storage -- a `DateTime(timezone=
    True)` column round-trips as a naive datetime on this dialect even
    though every value was written as UTC (Postgres does not have this
    issue). Every raw column read back into a pydantic model goes through
    this so callers never have to guess -- same defensive "never trust the
    read path alone" convention as app.news.normalization's own timestamp
    handling."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class SqlAlchemyNewsRepository(NewsRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        bind = session.get_bind()
        Base.metadata.create_all(
            bind=bind,
            tables=[
                NewsArticleRecord.__table__,
                CatalystEventRecord.__table__,
                CatalystEventArticleRecord.__table__,
                CatalystReactionRecord.__table__,
            ],
            checkfirst=True,
        )

    # ---- articles -----------------------------------------------------

    def upsert_articles(self, articles: list[NormalizedNewsArticle]) -> int:
        """Idempotent (#L): an article whose `article_id` already exists is
        skipped entirely, never duplicated and never overwritten -- the
        deterministic content-derived id (app.news.normalization) is what
        makes re-ingesting the same source article a safe no-op."""
        inserted = 0
        for article in articles:
            existing = self._session.execute(
                select(NewsArticleRecord).where(NewsArticleRecord.article_id == article.article_id)
            ).scalar_one_or_none()
            if existing is not None:
                continue
            self._session.add(
                NewsArticleRecord(
                    article_id=article.article_id,
                    provider=article.provider,
                    source=article.source,
                    headline=article.headline,
                    published_at=article.published_at,
                    received_at=article.received_at,
                    url=article.url,
                    symbols=list(article.symbols),
                    raw_category=article.raw_category,
                    category=article.classification.category.value,
                    classification=article.classification.model_dump(mode="json"),
                    provenance=article.provenance,
                )
            )
            inserted += 1
        self._session.commit()
        return inserted

    def get_articles_for_symbol(
        self, symbol: str, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]:
        symbol = symbol.upper()
        candidates = self._query_articles_in_range(start, end, as_of)
        return [a for a in candidates if symbol in a.symbols]

    def get_market_articles(
        self, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]:
        return self._query_articles_in_range(start, end, as_of)

    def _query_articles_in_range(
        self, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]:
        # Defensive re-filtering (#E): even though callers are expected to
        # pass an already-sane as_of, published_at <= as_of is enforced here
        # too, independent of caller correctness -- same "never trust the
        # caller alone for an anti-lookahead guarantee" convention
        # app.market_structure.common.truncate_to_as_of already established.
        effective_end = min(end, as_of)
        rows = self._session.execute(
            select(NewsArticleRecord).where(
                NewsArticleRecord.published_at >= start,
                NewsArticleRecord.published_at <= effective_end,
            )
        ).scalars()
        return [self._to_pydantic(row) for row in rows]

    def _to_pydantic(self, row: NewsArticleRecord) -> NormalizedNewsArticle:
        return NormalizedNewsArticle(
            article_id=row.article_id,
            provider=row.provider,
            source=row.source,
            headline=row.headline,
            published_at=_ensure_utc(row.published_at),
            received_at=_ensure_utc(row.received_at),
            url=row.url,
            symbols=tuple(row.symbols),
            raw_category=row.raw_category,
            classification=row.classification,
            provenance=row.provenance,
            ingested_at=_ensure_utc(row.ingested_at),
        )

    # ---- events ---------------------------------------------------------

    def events_for_symbol_as_of(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        as_of: datetime,
        config: CatalystConfig = DEFAULT_CATALYST_CONFIG,
    ) -> list[CatalystEvent]:
        articles = self.get_articles_for_symbol(symbol, start, end, as_of)
        return group_into_events(articles, config)

    def persist_events_snapshot(self, events: list[CatalystEvent]) -> None:
        """Best-effort cache write for the "current" listing views (#L) --
        never consulted by `events_for_symbol_as_of`. Idempotent: an
        `event_id` already present is left untouched."""
        for event in events:
            existing = self._session.execute(
                select(CatalystEventRecord).where(CatalystEventRecord.event_id == event.event_id)
            ).scalar_one_or_none()
            if existing is None:
                self._session.add(
                    CatalystEventRecord(
                        event_id=event.event_id,
                        primary_timestamp=event.primary_timestamp,
                        category=event.category.value,
                        affected_symbols=list(event.affected_symbols),
                        contributing_article_ids=list(event.contributing_article_ids),
                        source_count=event.source_count,
                        earliest_published_at=event.earliest_published_at,
                        latest_update_at=event.latest_update_at,
                        title=event.title,
                        provenance=event.provenance,
                        relevance=event.relevance.value,
                        primary_source=event.primary_source,
                        primary_url=event.primary_url,
                    )
                )
            for article_id in event.contributing_article_ids:
                existing_link = self._session.execute(
                    select(CatalystEventArticleRecord).where(
                        CatalystEventArticleRecord.event_id == event.event_id,
                        CatalystEventArticleRecord.article_id == article_id,
                    )
                ).scalar_one_or_none()
                if existing_link is None:
                    self._session.add(
                        CatalystEventArticleRecord(event_id=event.event_id, article_id=article_id)
                    )
        self._session.commit()

    def list_recent_events(self, *, limit: int = 50) -> list[CatalystEvent]:
        """Reads the persisted "current" snapshot directly -- NOT as_of-safe;
        only for a live "what's moving right now" view (see module
        docstring). Historical/research callers must use
        `events_for_symbol_as_of` instead."""
        rows = self._session.execute(
            select(CatalystEventRecord).order_by(CatalystEventRecord.primary_timestamp.desc()).limit(limit)
        ).scalars()
        return [self._event_from_row(row) for row in rows]

    def get_event_by_id(self, event_id: str) -> Optional[CatalystEvent]:
        row = self._session.execute(
            select(CatalystEventRecord).where(CatalystEventRecord.event_id == event_id)
        ).scalar_one_or_none()
        return self._event_from_row(row) if row is not None else None

    def get_articles_by_ids(self, article_ids: list[str]) -> list[NormalizedNewsArticle]:
        if not article_ids:
            return []
        rows = self._session.execute(
            select(NewsArticleRecord).where(NewsArticleRecord.article_id.in_(article_ids))
        ).scalars()
        return [self._to_pydantic(row) for row in rows]

    def _event_from_row(self, row: CatalystEventRecord) -> CatalystEvent:
        return CatalystEvent(
            event_id=row.event_id,
            primary_timestamp=_ensure_utc(row.primary_timestamp),
            category=row.category,
            affected_symbols=tuple(row.affected_symbols),
            contributing_article_ids=list(row.contributing_article_ids),
            source_count=row.source_count,
            earliest_published_at=_ensure_utc(row.earliest_published_at),
            latest_update_at=_ensure_utc(row.latest_update_at),
            title=row.title,
            provenance=row.provenance,
            relevance=row.relevance,
            primary_source=row.primary_source,
            primary_url=row.primary_url,
        )

    # ---- reactions --------------------------------------------------------

    def upsert_reaction(self, reaction: MarketReaction) -> None:
        existing = self._session.execute(
            select(CatalystReactionRecord).where(
                CatalystReactionRecord.event_id == reaction.event_id,
                CatalystReactionRecord.symbol == reaction.symbol,
                CatalystReactionRecord.timeframe == reaction.timeframe,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return  # deterministic given the same candles -- never overwritten
        self._session.add(
            CatalystReactionRecord(
                event_id=reaction.event_id,
                symbol=reaction.symbol,
                timeframe=reaction.timeframe,
                reaction=reaction.model_dump(mode="json"),
            )
        )
        self._session.commit()

    def get_reaction(self, event_id: str, symbol: str, timeframe: str) -> Optional[MarketReaction]:
        row = self._session.execute(
            select(CatalystReactionRecord).where(
                CatalystReactionRecord.event_id == event_id,
                CatalystReactionRecord.symbol == symbol,
                CatalystReactionRecord.timeframe == timeframe,
            )
        ).scalar_one_or_none()
        return MarketReaction.model_validate(row.reaction) if row is not None else None
