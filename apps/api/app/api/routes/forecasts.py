"""Phase 12 (#Q): Forward Prediction Benchmark & Validation Lab API. Thin
orchestration only -- app.forecasting.service/resolver/metrics/gate do all
the real work, same "no logic lives in a route" convention every other
route module in this codebase follows.

`POST /{symbol}` never accepts a `market_as_of` parameter -- this is the
mechanical enforcement behind "never backfill a prospective forecast" (#J):
there is structurally no way to ask this route to create a forecast for a
past instant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai_analysis.evidence_packet import SetupNotFoundError
from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.api.deps import get_market_data_provider, get_news_provider
from app.api.routes.market import _validated_symbol, _validated_timeframe
from app.database.session import get_db
from app.forecasting import metrics as metrics_module
from app.forecasting.baselines import BaselineResult, compute_baselines
from app.forecasting.gate import GATE_V1_CRITERIA, GATE_VERSION, GateEvaluation, evaluate_gate
from app.forecasting.metrics import PerformanceBreakdown
from app.forecasting.repository import SqlAlchemyForecastRepository
from app.forecasting.resolver import resolve_forecast
from app.forecasting.schemas import ForecastCategory, ForecastOrigin, ForecastOutcome, ForwardForecast
from app.forecasting.service import create_forecast
from app.market_data.provider import MarketDataProvider
from app.news.provider import NewsProvider
from app.news.repository import SqlAlchemyNewsRepository
from app.research.repository import SqlAlchemyResearchRepository

router = APIRouter(prefix="/api/forecasts", tags=["forecasts"])


def _news_repository(db: Session = Depends(get_db)) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(db)


def _research_repository(db: Session = Depends(get_db)) -> SqlAlchemyResearchRepository:
    return SqlAlchemyResearchRepository(db)


def _evidence_repository(db: Session = Depends(get_db)) -> SqlAlchemyEvidenceRepository:
    return SqlAlchemyEvidenceRepository(db)


def _forecast_repository(db: Session = Depends(get_db)) -> SqlAlchemyForecastRepository:
    return SqlAlchemyForecastRepository(db)


class CreateForecastRequest(BaseModel):
    symbol: str
    timeframe: str = "1h"
    forecast_category: ForecastCategory
    horizon_bars: int = 5
    setup_id: str | None = None
    origin: ForecastOrigin = ForecastOrigin.DETERMINISTIC_RESEARCH


@router.post("", response_model=ForwardForecast)
def post_forecast(
    body: CreateForecastRequest,
    market_provider: MarketDataProvider = Depends(get_market_data_provider),
    news_provider: NewsProvider = Depends(get_news_provider),
    news_repository: SqlAlchemyNewsRepository = Depends(_news_repository),
    research_repository: SqlAlchemyResearchRepository = Depends(_research_repository),
    evidence_repository: SqlAlchemyEvidenceRepository = Depends(_evidence_repository),
    forecast_repository: SqlAlchemyForecastRepository = Depends(_forecast_repository),
) -> ForwardForecast:
    validated_symbol = _validated_symbol(body.symbol)
    validated_timeframe = _validated_timeframe(body.timeframe)

    try:
        return create_forecast(
            symbol=validated_symbol,
            timeframe=validated_timeframe,
            forecast_category=body.forecast_category,
            horizon_bars=body.horizon_bars,
            setup_id=body.setup_id,
            origin=body.origin,
            market_provider=market_provider,
            news_provider=news_provider,
            news_repository=news_repository,
            research_repository=research_repository,
            evidence_repository=evidence_repository,
            forecast_repository=forecast_repository,
        )
    except SetupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[ForwardForecast])
def list_forecasts(
    symbol: str | None = Query(None),
    timeframe: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    forecast_repository: SqlAlchemyForecastRepository = Depends(_forecast_repository),
) -> list[ForwardForecast]:
    return forecast_repository.list_forecasts(symbol=symbol, timeframe=timeframe, status=status, limit=limit)


@router.get("/performance")
def get_performance(
    symbol: str | None = Query(None),
    forecast_repository: SqlAlchemyForecastRepository = Depends(_forecast_repository),
) -> dict:
    forecasts = forecast_repository.list_forecasts(symbol=symbol, limit=5000)
    outcomes = forecast_repository.list_outcomes([f.forecast_id for f in forecasts])

    def _dump(breakdowns: list[PerformanceBreakdown]) -> list[dict]:
        return [b.__dict__ for b in breakdowns]

    def _dump_baselines(baselines: list[BaselineResult]) -> list[dict]:
        return [b.__dict__ for b in baselines]

    return {
        "overall": metrics_module.overall_performance(forecasts, outcomes).__dict__,
        "by_symbol": _dump(metrics_module.by_symbol(forecasts, outcomes)),
        "by_timeframe": _dump(metrics_module.by_timeframe(forecasts, outcomes)),
        "by_setup_type": _dump(metrics_module.by_setup_type(forecasts, outcomes)),
        "by_catalyst_category": _dump(metrics_module.by_catalyst_category(forecasts, outcomes)),
        "by_evidence_quality": _dump(metrics_module.by_evidence_quality(forecasts, outcomes)),
        "by_origin": _dump(metrics_module.by_origin(forecasts, outcomes)),
        "by_horizon": _dump(metrics_module.by_horizon(forecasts, outcomes)),
        "baselines": _dump_baselines(compute_baselines(forecasts, outcomes)),
    }


@router.get("/gate")
def get_gate(
    forecast_repository: SqlAlchemyForecastRepository = Depends(_forecast_repository),
) -> dict:
    forecasts = forecast_repository.list_forecasts(limit=5000)
    outcomes = forecast_repository.list_outcomes([f.forecast_id for f in forecasts])

    forecast_repository.save_gate_version(GATE_VERSION, GATE_V1_CRITERIA.__dict__)
    evaluation: GateEvaluation = evaluate_gate(forecasts, outcomes)
    forecast_repository.save_gate_result(
        GATE_VERSION, datetime.now(timezone.utc), evaluation.decision.value, evaluation.__dict__
    )
    return {
        **evaluation.__dict__,
        "decision": evaluation.decision.value,
        "criteria": GATE_V1_CRITERIA.__dict__,
    }


@router.get("/{forecast_id}", response_model=ForwardForecast)
def get_forecast(
    forecast_id: str, forecast_repository: SqlAlchemyForecastRepository = Depends(_forecast_repository)
) -> ForwardForecast:
    forecast = forecast_repository.get_forecast(forecast_id)
    if forecast is None:
        raise HTTPException(status_code=404, detail=f"Forecast {forecast_id!r} not found")
    return forecast


@router.post("/{forecast_id}/resolve", response_model=ForecastOutcome)
def resolve(
    forecast_id: str,
    market_provider: MarketDataProvider = Depends(get_market_data_provider),
    news_repository: SqlAlchemyNewsRepository = Depends(_news_repository),
    evidence_repository: SqlAlchemyEvidenceRepository = Depends(_evidence_repository),
    forecast_repository: SqlAlchemyForecastRepository = Depends(_forecast_repository),
) -> ForecastOutcome:
    forecast = forecast_repository.get_forecast(forecast_id)
    if forecast is None:
        raise HTTPException(status_code=404, detail=f"Forecast {forecast_id!r} not found")

    existing = forecast_repository.get_outcome_for_forecast(forecast_id)
    if existing is not None:
        return existing

    outcome = resolve_forecast(
        forecast, market_provider, evidence_repository, news_repository=news_repository
    )
    forecast_repository.save_outcome(outcome)
    return outcome
