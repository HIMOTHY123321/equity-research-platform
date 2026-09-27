"""Phase 16 (§8/§28/§29): the standalone background-worker entrypoint --
runs the exact same LiveMarketService/RecomputationEngine/ForecastMonitor/
NewsMonitor/MonitoringService singletons app.main's lifespan constructs
for "combined" mode, but with no FastAPI app / HTTP server at all.

Run with:

    python -m app.worker

Multi-replica deployments must run exactly ONE of these per environment
(never one per web replica -- see app.config.Settings.worker_mode's own
docstring for why) alongside any number of "api"-mode web replicas.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.api.deps import (
    get_market_data_provider,
    get_news_provider,
    get_session_factory,
    get_shared_market_data_cache,
    get_streaming_provider,
)
from app.config import get_settings
from app.database.models import Base
from app.database.session import engine
from app.live.config import DEFAULT_LIVE_CONFIG
from app.live.forecast_monitor import ForecastMonitor
from app.live.news_monitor import NewsMonitor
from app.live.recompute import RecomputationEngine
from app.live.service import LiveMarketService
from app.monitoring.service import MonitoringService

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    Base.metadata.create_all(bind=engine, checkfirst=True)

    market_provider = get_market_data_provider()
    news_provider = get_news_provider()
    streaming_provider = get_streaming_provider()
    cache = get_shared_market_data_cache()
    session_factory = get_session_factory()

    live_service = LiveMarketService(
        market_provider,
        provider_name=settings.market_data_provider,
        config=DEFAULT_LIVE_CONFIG,
        streaming_provider=streaming_provider,
    )
    recompute_engine = RecomputationEngine(live_service, market_provider, cache)
    forecast_monitor = ForecastMonitor(
        session_factory, market_provider, news_provider, config=DEFAULT_LIVE_CONFIG
    )
    news_monitor = NewsMonitor(session_factory, news_provider, config=DEFAULT_LIVE_CONFIG)
    monitoring_service = MonitoringService(session_factory, market_provider, config=DEFAULT_LIVE_CONFIG)

    await recompute_engine.start()
    await forecast_monitor.start()
    await news_monitor.start()
    await monitoring_service.start()
    logger.info("Worker started: recompute engine, forecast monitor, news monitor, monitoring service")

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        logger.info("Worker received shutdown signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # Windows: add_signal_handler is unsupported for SIGTERM; the
            # process still exits cleanly on Ctrl+C via KeyboardInterrupt.
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("Worker shutting down")
        await monitoring_service.stop()
        await news_monitor.stop()
        await forecast_monitor.stop()
        await recompute_engine.stop()
        await live_service.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
