"""Phase 12.1 (#I/#K): background forecast resolution. A real asyncio
background task, started once at process startup (app.main's lifespan) and
completely independent of any HTTP request or React page lifecycle -- it
keeps scanning and resolving ACTIVE prospective forecasts for as long as
the backend process runs, whether or not Forecast Lab is open.

Calls app.forecasting.resolver.resolve_forecast unchanged -- this module
adds *scheduling*, never a second resolution implementation. The original
ForwardForecast remains exactly as immutable as it always was; only when
and how often resolve_forecast gets called is new here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.forecasting.repository import SqlAlchemyForecastRepository
from app.forecasting.resolver import resolve_forecast
from app.forecasting.schemas import ForecastOutcome, ForecastOutcomeCategory
from app.live.config import DEFAULT_LIVE_CONFIG, LiveConfig
from app.market_data.provider import MarketDataProvider
from app.news.provider import NewsProvider
from app.news.repository import SqlAlchemyNewsRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForecastResolvedEvent:
    forecast_id: str
    symbol: str
    outcome: ForecastOutcome


class ForecastMonitor:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        market_provider: MarketDataProvider,
        news_provider: Optional[NewsProvider] = None,
        config: LiveConfig = DEFAULT_LIVE_CONFIG,
        now_fn=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._session_factory = session_factory
        self._market_provider = market_provider
        self._news_provider = news_provider
        self._config = config
        self._now = now_fn
        self._task: Optional[asyncio.Task] = None
        self._listeners: list[asyncio.Queue] = []

    def add_listener(self) -> "asyncio.Queue[ForecastResolvedEvent]":
        queue: "asyncio.Queue[ForecastResolvedEvent]" = asyncio.Queue()
        self._listeners.append(queue)
        return queue

    def remove_listener(self, queue: "asyncio.Queue[ForecastResolvedEvent]") -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def scan_and_resolve_once(self) -> list[ForecastResolvedEvent]:
        """The directly-testable core: one full scan of ACTIVE forecasts,
        resolving whichever ones genuinely can be. Never persists an
        INSUFFICIENT_FUTURE_DATA attempt (same rule as the manual RESOLVE
        route -- see app.api.routes.forecasts -- a too-early scan must
        never permanently lock a forecast out of resolving later)."""
        session = self._session_factory()
        try:
            forecast_repository = SqlAlchemyForecastRepository(session)
            evidence_repository = SqlAlchemyEvidenceRepository(session)
            news_repository = SqlAlchemyNewsRepository(session)

            resolved_events: list[ForecastResolvedEvent] = []
            for forecast in forecast_repository.list_forecasts(status="active", limit=1000):
                if forecast_repository.get_outcome_for_forecast(forecast.forecast_id) is not None:
                    continue
                try:
                    outcome = resolve_forecast(
                        forecast,
                        self._market_provider,
                        evidence_repository,
                        news_provider=self._news_provider,
                        news_repository=news_repository,
                        now=self._now(),
                    )
                except Exception:
                    logger.exception("Auto-resolution failed for forecast %s", forecast.forecast_id)
                    continue

                if outcome.outcome == ForecastOutcomeCategory.INSUFFICIENT_FUTURE_DATA:
                    continue  # try again on the next scan -- never persisted

                forecast_repository.save_outcome(outcome)
                event = ForecastResolvedEvent(
                    forecast_id=forecast.forecast_id, symbol=forecast.symbol, outcome=outcome
                )
                resolved_events.append(event)
                for queue in list(self._listeners):
                    queue.put_nowait(event)
            return resolved_events
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
                    await asyncio.to_thread(self.scan_and_resolve_once)
                except Exception:
                    logger.exception("Forecast monitor scan failed")
                await asyncio.sleep(self._config.forecast_monitor_interval_seconds)
        except asyncio.CancelledError:
            return
