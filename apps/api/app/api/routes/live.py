"""Phase 12.1 (#P/#Q/#Y): WS /api/live/stream -- one WebSocket connection
fans out quote/forming-candle/completed-candle/forecast/catalyst/freshness/
connection-status events from the shared, process-wide LiveMarketService/
RecomputationEngine/ForecastMonitor/NewsMonitor singletons (app.state,
started once in app.main's lifespan). Every browser tab subscribing to SPY
shares the exact same upstream poll loop -- this route never starts a new
one (#O).

WebSocket chosen over SSE (documented in ADR 0017): the client genuinely
needs to send subscribe/unsubscribe messages back, not just receive a
one-way stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.live.config import DEFAULT_LIVE_CONFIG, SubscriptionPriority
from app.live.forecast_monitor import ForecastResolvedEvent
from app.live.news_monitor import NewEvidenceEvent
from app.live.recompute import SnapshotRefreshedEvent
from app.schemas.market_data import Timeframe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live"])

_PRIORITY_BY_NAME = {p.value: p for p in SubscriptionPriority}


class SubscribeMessage(BaseModel):
    action: Literal["subscribe"]
    symbol: str
    timeframes: list[str] = ["1h"]
    priority: str = "viewed"


class UnsubscribeMessage(BaseModel):
    action: Literal["unsubscribe"]
    symbol: str


def _event_to_frame(event: object) -> Optional[dict]:
    """A closed, typed set of server events (#Y) serialized to one flat
    JSON shape the frontend switches on by `type` -- never an ad hoc dict."""
    module = type(event).__module__
    name = type(event).__name__

    if name == "QuoteEvent":
        return {"type": "quote", "symbol": event.symbol, "quote": event.quote.model_dump(mode="json")}
    if name == "FormingCandleEvent":
        return {
            "type": "forming_candle",
            "symbol": event.symbol,
            "candle": event.candle.model_dump(mode="json"),
        }
    if name == "CompletedCandleEvent":
        return {
            "type": "completed_candle",
            "symbol": event.symbol,
            "candle": event.candle.model_dump(mode="json"),
        }
    if name == "ConnectionStatusEvent":
        return {"type": "connection_status", "status": event.status.model_dump(mode="json")}
    if isinstance(event, SnapshotRefreshedEvent):
        return {
            "type": "snapshot_refreshed",
            "symbol": event.symbol,
            "timeframe": event.timeframe.value,
            "refreshed_at": event.refreshed_at.isoformat(),
        }
    if isinstance(event, ForecastResolvedEvent):
        return {
            "type": "forecast_resolved",
            "forecast_id": event.forecast_id,
            "symbol": event.symbol,
            "outcome": event.outcome.model_dump(mode="json"),
        }
    if isinstance(event, NewEvidenceEvent):
        return {
            "type": "catalyst_event",
            "symbol": event.symbol,
            "new_article_count": event.new_article_count,
            "detected_at": event.detected_at.isoformat(),
        }
    logger.warning("Unrecognized live event type %s.%s -- dropped, not forwarded", module, name)
    return None


async def _forward(source_queue: "asyncio.Queue", outbound: "asyncio.Queue") -> None:
    while True:
        event = await source_queue.get()
        frame = _event_to_frame(event)
        if frame is not None:
            outbound.put_nowait(frame)


async def _heartbeat(outbound: "asyncio.Queue", interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        outbound.put_nowait({"type": "heartbeat"})


@router.get("/status")
def live_status(request: Request) -> dict:
    live_service = request.app.state.live_service
    capabilities = live_service.provider_capabilities()
    return {
        "capabilities": {
            "real_time_quotes": capabilities.real_time_quotes,
            "streaming_quotes": capabilities.streaming_quotes,
            "streaming_trades": capabilities.streaming_trades,
            "streaming_bars": capabilities.streaming_bars,
            "streaming_news": capabilities.streaming_news,
            "historical_intraday": capabilities.historical_intraday,
            "quote_delay_seconds": capabilities.quote_delay_seconds,
            "news_delay_seconds": capabilities.news_delay_seconds,
            "min_poll_interval_seconds": capabilities.min_poll_interval_seconds,
        },
        # (Phase 12.2 §O) truthful, not "WebSocket transport used therefore
        # real-time" -- False whenever no streaming provider is actually
        # configured/available, in which case connection_status still
        # reflects the Phase 12.1 poll loop.
        "streaming_active": live_service.is_streaming(),
        "connection_status": live_service.connection_status().model_dump(mode="json"),
        "latency": [
            {
                "event_type": entry.event_type,
                "symbol": entry.symbol,
                "provider": entry.provider,
                "count": entry.count,
                "median_seconds": entry.median_seconds,
                "p95_seconds": entry.p95_seconds,
                "p99_seconds": entry.p99_seconds,
                "max_seconds": entry.max_seconds,
            }
            for entry in live_service.latency_summary()
        ],
    }


@router.websocket("/stream")
async def live_stream(websocket: WebSocket) -> None:
    app_state = websocket.app.state
    live_service = app_state.live_service
    recompute_engine = getattr(app_state, "recompute_engine", None)
    forecast_monitor = getattr(app_state, "forecast_monitor", None)
    news_monitor = getattr(app_state, "news_monitor", None)
    live_config = getattr(app_state, "live_config", DEFAULT_LIVE_CONFIG)

    await websocket.accept()

    outbound: "asyncio.Queue[dict]" = asyncio.Queue()
    subscribed_symbols: set[str] = set()

    # connection_status events are only published on a *transition*
    # (LiveMarketService._set_connection_state) -- a brand-new connection
    # made while the service is already CONNECTED from an earlier
    # subscriber would otherwise never learn the current state at all and
    # sit on a client-side default of DISCONNECTED forever. Every
    # connection gets an explicit snapshot immediately on accept.
    outbound.put_nowait(
        {"type": "connection_status", "status": live_service.connection_status().model_dump(mode="json")}
    )

    live_queue = live_service.add_listener()
    recompute_queue = recompute_engine.add_listener() if recompute_engine else None
    forecast_queue = forecast_monitor.add_listener() if forecast_monitor else None
    news_queue = news_monitor.add_listener() if news_monitor else None

    background_tasks = [asyncio.create_task(_forward(live_queue, outbound))]
    if recompute_queue is not None:
        background_tasks.append(asyncio.create_task(_forward(recompute_queue, outbound)))
    if forecast_queue is not None:
        background_tasks.append(asyncio.create_task(_forward(forecast_queue, outbound)))
    if news_queue is not None:
        background_tasks.append(asyncio.create_task(_forward(news_queue, outbound)))
    background_tasks.append(asyncio.create_task(_heartbeat(outbound, live_config.heartbeat_interval_seconds)))

    # Every subscribed-symbol event is broadcast to every connection (the
    # shared-listener design #O); this connection only ever forwards on the
    # symbols it actually asked for.
    async def _writer() -> None:
        while True:
            frame = await outbound.get()
            symbol = frame.get("symbol")
            if symbol is not None and symbol not in subscribed_symbols:
                continue
            await websocket.send_json(frame)

    writer_task = asyncio.create_task(_writer())

    try:
        while True:
            raw = await websocket.receive_json()
            action = raw.get("action")
            try:
                if action == "subscribe":
                    message = SubscribeMessage.model_validate(raw)
                    timeframes = tuple(Timeframe(tf) for tf in message.timeframes)
                    priority = _PRIORITY_BY_NAME.get(message.priority, SubscriptionPriority.VIEWED)
                    await live_service.subscribe(message.symbol, priority, timeframes)
                    if news_monitor is not None:
                        news_monitor.subscribe(message.symbol)
                    subscribed_symbols.add(message.symbol)
                    # Hardening pass regression fix, same shape as the
                    # Phase 12.1 connection_status snapshot-on-connect fix:
                    # quote/forming_candle events are only ever published on
                    # a genuine *new* observation (correctly, post-hardening
                    # -- see LiveMarketService's dedup). Before that fix,
                    # yfinance's fabricated now() timestamp meant a "new"
                    # quote arrived on nearly every poll, which accidentally
                    # papered over the real gap: a freshly-subscribing
                    # connection otherwise never learns state that was
                    # already known *before* it subscribed, sometimes for
                    # minutes (yfinance's real polling floor). Send an
                    # explicit snapshot of whatever this service already
                    # knows, directly to this connection only.
                    existing_quote = live_service.latest_quote(message.symbol)
                    if existing_quote is not None:
                        outbound.put_nowait(
                            {
                                "type": "quote",
                                "symbol": message.symbol,
                                "quote": existing_quote.model_dump(mode="json"),
                            }
                        )
                    for timeframe in timeframes:
                        existing_candle = live_service.latest_candle(message.symbol, timeframe)
                        if existing_candle is not None:
                            outbound.put_nowait(
                                {
                                    "type": "forming_candle",
                                    "symbol": message.symbol,
                                    "candle": existing_candle.model_dump(mode="json"),
                                }
                            )
                elif action == "unsubscribe":
                    message = UnsubscribeMessage.model_validate(raw)
                    await live_service.unsubscribe(message.symbol)
                    subscribed_symbols.discard(message.symbol)
                else:
                    await websocket.send_json({"type": "error", "detail": f"Unknown action {action!r}"})
            except (ValidationError, ValueError) as exc:
                await websocket.send_json({"type": "error", "detail": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        writer_task.cancel()
        for task in background_tasks:
            task.cancel()
        for task in [writer_task, *background_tasks]:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        live_service.remove_listener(live_queue)
        if recompute_engine and recompute_queue is not None:
            recompute_engine.remove_listener(recompute_queue)
        if forecast_monitor and forecast_queue is not None:
            forecast_monitor.remove_listener(forecast_queue)
        if news_monitor and news_queue is not None:
            news_monitor.remove_listener(news_queue)
        for symbol in list(subscribed_symbols):
            await live_service.unsubscribe(symbol)
