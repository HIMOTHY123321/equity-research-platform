"""Phase 12: forecast-creation orchestration. `create_forecast` is the one
place a ForwardForecast comes into existence.

Prospective-vs-backtest is enforced structurally, not by a runtime check
that could be bypassed: `market_as_of` is never a parameter the public API
route passes. Omitting it (the only path `app/api/routes/forecasts.py`
ever takes) builds the EvidencePacket with `as_of=None`, i.e. "right now" --
`run_mode` is PROSPECTIVE and the packet's own `mode` is LIVE. Supplying an
explicit `market_as_of` (only ever done by tests, exercising the resolver
against historical fixtures) tags the forecast BACKTEST_REPLAY instead --
app.forecasting.gate already excludes non-prospective forecasts from the
Forward Validation Gate, so a backtest row can never masquerade as
prospective evidence (#J).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from app.ai_analysis.claims import derive_evidence_claims
from app.ai_analysis.evidence_packet import build_evidence_packet
from app.ai_analysis.repository import EvidenceRepository
from app.forecasting.ai_forecast import (
    ForecastSelectionProvider,
    MockForecastSelectionProvider,
    select_ai_forecast,
)
from app.forecasting.config import DEFAULT_FORECAST_CONFIG, ForecastConfig
from app.forecasting.deterministic import generate_deterministic_forecast
from app.forecasting.repository import ForecastRepository
from app.forecasting.schemas import (
    ForecastCategory,
    ForecastOrigin,
    ForecastRunMode,
    ForecastStatus,
    ForwardForecast,
)
from app.research.repository import ResearchRepository
from app.schemas.market_data import Timeframe

if TYPE_CHECKING:
    from app.market_data.provider import MarketDataProvider
    from app.news.provider import NewsProvider
    from app.news.repository import NewsRepository


def _forecast_id(
    symbol: str, timeframe: str, market_as_of: datetime, category: ForecastCategory, packet_id: str
) -> str:
    digest_source = f"{symbol}|{timeframe}|{market_as_of.isoformat()}|{category.value}|{packet_id}"
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]


def create_forecast(
    *,
    symbol: str,
    timeframe: Timeframe,
    forecast_category: ForecastCategory,
    horizon_bars: int,
    market_provider: "MarketDataProvider",
    news_provider: "NewsProvider",
    news_repository: "NewsRepository",
    research_repository: ResearchRepository,
    evidence_repository: EvidenceRepository,
    forecast_repository: ForecastRepository,
    setup_id: Optional[str] = None,
    origin: ForecastOrigin = ForecastOrigin.DETERMINISTIC_RESEARCH,
    ai_provider: Optional[ForecastSelectionProvider] = None,
    market_as_of: Optional[datetime] = None,
    config: ForecastConfig = DEFAULT_FORECAST_CONFIG,
) -> ForwardForecast:
    run_mode = ForecastRunMode.PROSPECTIVE if market_as_of is None else ForecastRunMode.BACKTEST_REPLAY

    packet = build_evidence_packet(
        symbol=symbol,
        timeframe=timeframe,
        market_provider=market_provider,
        news_provider=news_provider,
        news_repository=news_repository,
        research_repository=research_repository,
        setup_id=setup_id,
        as_of=market_as_of,
    )
    evidence_repository.save_packet(packet)

    if origin == ForecastOrigin.DETERMINISTIC_RESEARCH:
        decision = generate_deterministic_forecast(packet, forecast_category, config)
        provider_name = model_name = prompt_version = None
    else:
        claims = derive_evidence_claims(packet)
        provider = ai_provider or MockForecastSelectionProvider()
        decision = select_ai_forecast(packet, claims, forecast_category, provider, config)
        provider_name = provider.name
        model_name = None
        prompt_version = None

    forecast_id = _forecast_id(symbol, timeframe.value, packet.as_of, forecast_category, packet.packet_id)

    forecast = ForwardForecast(
        forecast_id=forecast_id,
        created_at=datetime.now(timezone.utc),
        market_as_of=packet.as_of,
        symbol=symbol,
        timeframe=timeframe.value,
        forecast_category=forecast_category,
        forecast_value=decision.forecast_value,
        forecast_horizon_bars=horizon_bars,
        zone_ref=decision.zone_ref,
        evidence_packet_id=packet.packet_id,
        evidence_packet_schema_version=packet.schema_version,
        pipeline_version=packet.pipeline_version,
        evidence_refs=decision.evidence_refs,
        evidence_quality=decision.evidence_quality,
        origin=origin,
        provider=provider_name,
        model=model_name,
        prompt_version=prompt_version,
        status=ForecastStatus.ABSTAINED if decision.abstained else ForecastStatus.ACTIVE,
        abstention_reason=decision.abstention_reason,
        rationale=decision.rationale,
        run_mode=run_mode,
        setup_type=packet.setup.candidate.setup_type.value if packet.setup is not None else None,
        catalyst_category=(
            packet.catalyst_context.nearest_catalyst.category.value
            if packet.catalyst_context is not None and packet.catalyst_context.nearest_catalyst is not None
            else None
        ),
    )
    forecast_repository.save_forecast(forecast)
    return forecast
