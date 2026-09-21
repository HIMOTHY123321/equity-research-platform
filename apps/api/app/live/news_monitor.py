"""Phase 12.1 (#L/#M): background news/catalyst polling. yfinance's news
surface has no streaming option either (app.news.yfinance_provider), so
this is a provider-safe poll loop -- never a claimed push feed. Reuses the
exact ingestion -> normalization -> classification -> grouping pipeline
`GET /api/news/{symbol}`/`GET /api/catalysts/{symbol}` already run
per-request (`provider.fetch_symbol_news` -> `repository.upsert_articles`
-> `repository.events_for_symbol_as_of` -> `repository.persist_events_
snapshot`); this module only adds a timer on top, never a second pipeline.

Never regenerates an existing frozen ResearchBrief (#M) -- this module has
no access to, and never calls, app.ai_analysis.brief at all. It only
detects that genuinely new articles exist and reports that fact
(NewEvidenceEvent) for a caller (the WS route) to surface as "NEW EVIDENCE
AVAILABLE"; creating a new EvidencePacket/brief version remains an explicit
user action.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.live.config import DEFAULT_LIVE_CONFIG, LiveConfig
from app.news.provider import NewsProvider
from app.news.repository import SqlAlchemyNewsRepository

logger = logging.getLogger(__name__)

_NEW_ARTICLE_LOOKBACK = timedelta(days=1)


@dataclass(frozen=True)
class NewEvidenceEvent:
    symbol: str
    new_article_count: int
    detected_at: datetime


class NewsMonitor:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        news_provider: NewsProvider,
        config: LiveConfig = DEFAULT_LIVE_CONFIG,
        now_fn=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._session_factory = session_factory
        self._news_provider = news_provider
        self._config = config
        self._now = now_fn
        self._subscribed_symbols: set[str] = set()
        # Per-symbol baseline of already-seen article ids -- only a
        # *subsequent* scan finding an id outside this set counts as new
        # evidence; the first scan for a symbol only establishes the
        # baseline; it never floods a fresh subscription with "new" events
        # for articles that were already there.
        self._known_article_ids: dict[str, set[str]] = {}
        self._task: Optional[asyncio.Task] = None
        self._listeners: list[asyncio.Queue] = []

    def subscribe(self, symbol: str) -> None:
        self._subscribed_symbols.add(symbol)

    def unsubscribe(self, symbol: str) -> None:
        self._subscribed_symbols.discard(symbol)
        self._known_article_ids.pop(symbol, None)

    def add_listener(self) -> "asyncio.Queue[NewEvidenceEvent]":
        queue: "asyncio.Queue[NewEvidenceEvent]" = asyncio.Queue()
        self._listeners.append(queue)
        return queue

    def remove_listener(self, queue: "asyncio.Queue[NewEvidenceEvent]") -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def scan_once(self) -> list[NewEvidenceEvent]:
        """The directly-testable core: one pass over every subscribed
        symbol -- fetch, normalize/persist (idempotent -- an already-known
        article_id is a no-op), regroup into catalyst events, and detect
        whether any article id is genuinely new since the last scan."""
        session = self._session_factory()
        try:
            news_repository = SqlAlchemyNewsRepository(session)
            now = self._now()
            start = now - _NEW_ARTICLE_LOOKBACK
            events: list[NewEvidenceEvent] = []

            for symbol in sorted(self._subscribed_symbols):
                try:
                    fetched = self._news_provider.fetch_symbol_news(symbol, start, now, now)
                    news_repository.upsert_articles(fetched)
                except Exception:
                    logger.warning("News poll failed for %s", symbol, exc_info=True)
                    continue

                articles = news_repository.get_articles_for_symbol(symbol, start, now, now)
                current_ids = {a.article_id for a in articles}

                # Catalyst grouping refresh (#L) -- same call
                # GET /api/catalysts/{symbol} already makes, reused verbatim.
                grouped = news_repository.events_for_symbol_as_of(symbol, start, now, now)
                news_repository.persist_events_snapshot(grouped)

                previously_known = self._known_article_ids.get(symbol)
                if previously_known is not None:
                    new_ids = current_ids - previously_known
                    if new_ids:
                        event = NewEvidenceEvent(
                            symbol=symbol, new_article_count=len(new_ids), detected_at=now
                        )
                        events.append(event)
                        for queue in list(self._listeners):
                            queue.put_nowait(event)
                self._known_article_ids[symbol] = current_ids

            return events
        finally:
            session.close()

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        try:
            while True:
                try:
                    await asyncio.to_thread(self.scan_once)
                except Exception:
                    logger.exception("News monitor scan failed")
                await asyncio.sleep(self._config.news_monitor_interval_seconds)
        except asyncio.CancelledError:
            return
