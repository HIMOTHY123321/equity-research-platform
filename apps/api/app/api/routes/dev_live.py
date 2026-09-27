"""Phase 17 (§60/§79/§99): /api/dev/live-simulator -- a hand-scriptable
trigger for app.live.mock_streaming.MockStreamingProvider so a developer
can preview live-chart UX (forming/completed candles, reconnect/gap-fill,
connection status) without any real provider account.

Every route here 404s unless BOTH settings.enable_dev_live_simulator is
true AND environment is not production -- the config validator
(Settings._validate_production_safety) already makes that combination
impossible to configure in production at all, and app.main's lifespan only
ever sets app.state.dev_mock_streaming_provider under the same condition,
so this is unreachable in production by construction, not just by a
runtime check. Events pushed here flow through the real
LiveMarketService/RecomputationEngine pipeline the same way a genuine
provider's events would -- this file never fabricates candles/events
itself, it only lets a developer script the upstream provider's output.

CRITICAL (§80): a mock-provider event can never count as prospective
research -- app.main wires provider_name="mock" whenever this simulator is
active, and app.live.entitlement.resolve_streaming_entitlement only ever
resolves ENTITLED for provider "massive", so real_time_available() is
always False here. See tests/unit/live/test_dev_live_simulator.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.live.streaming import StreamTrade

router = APIRouter(prefix="/api/dev/live-simulator", tags=["dev"])


def _require_simulator(request: Request):
    provider = getattr(request.app.state, "dev_mock_streaming_provider", None)
    if provider is None:
        # Deliberately a plain 404, not a 403 -- outside dev this route
        # must look like it doesn't exist, not like a protected resource.
        raise HTTPException(status_code=404, detail="Not Found")
    return provider


@router.get("/status")
def simulator_status(request: Request) -> dict:
    provider = _require_simulator(request)
    return {
        "enabled": True,
        "connected": provider.connected,
        "connect_count": provider.connect_count,
        "subscriptions": {symbol: sorted(channels) for symbol, channels in provider.subscriptions.items()},
    }


class TradeMessage(BaseModel):
    symbol: str
    price: float
    size: float = 100.0
    exchange: Optional[int] = None
    sequence: Optional[int] = None


@router.post("/trade")
def push_trade(request: Request, message: TradeMessage) -> dict:
    provider = _require_simulator(request)
    provider.push_event(
        StreamTrade(
            symbol=message.symbol.upper(),
            price=message.price,
            size=message.size,
            exchange=message.exchange,
            conditions=(),
            source_timestamp=datetime.now(timezone.utc),
            sequence=message.sequence,
        )
    )
    return {"pushed": True}


@router.post("/disconnect")
def push_disconnect(request: Request) -> dict:
    """Simulate a dropped upstream connection, to preview reconnect/
    RESYNCING UX and (after a long-enough simulated gap) gap-fill."""
    provider = _require_simulator(request)
    provider.push_disconnect()
    return {"pushed": True}
