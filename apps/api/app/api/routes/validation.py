"""Phase 15: Prospective Validation & Signal Qualification API. Thin
orchestration only -- app.validation.{dataset,cohort,gate,comparison,
service} do all the real work, same convention every other route module
in this codebase follows.

Research only. No BUY/SELL, probability, or confidence-score field is
ever returned by any route in this module.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository, SqlAlchemyAlertRepository
from app.database.session import get_db
from app.decision_engine.repository import DecisionEngineRepository, SqlAlchemyDecisionEngineRepository
from app.research.repository import ResearchRepository, SqlAlchemyResearchRepository
from app.schemas.market_data import Timeframe
from app.validation.cohort import build_cohort_statistics
from app.validation.comparison import compare_historical_vs_prospective, historical_returns_for_cohort
from app.validation.dataset import build_prospective_dataset
from app.validation.gate import SIGNAL_GATE_V1_CRITERIA, SIGNAL_GATE_VERSION
from app.validation.repository import SignalGateRepository, SqlAlchemySignalGateRepository
from app.validation.service import build_summary, evaluate_and_persist_gate, observation_status

router = APIRouter(prefix="/api/validation", tags=["validation"])


def _alert_repository(db: Session = Depends(get_db)) -> AlertRepository:
    return SqlAlchemyAlertRepository(db)


def _decision_repository(db: Session = Depends(get_db)) -> DecisionEngineRepository:
    return SqlAlchemyDecisionEngineRepository(db)


def _research_repository(db: Session = Depends(get_db)) -> ResearchRepository:
    return SqlAlchemyResearchRepository(db)


def _gate_repository(db: Session = Depends(get_db)) -> SignalGateRepository:
    return SqlAlchemySignalGateRepository(db)


@router.get("/status")
def get_status(
    alert_repository: AlertRepository = Depends(_alert_repository),
    decision_repository: DecisionEngineRepository = Depends(_decision_repository),
) -> dict:
    observations = build_prospective_dataset(alert_repository, decision_repository)
    return observation_status(observations)


@router.get("/gate")
def get_gate(
    timeframe: Timeframe = Query(default=Timeframe.ONE_HOUR),
    alert_repository: AlertRepository = Depends(_alert_repository),
    decision_repository: DecisionEngineRepository = Depends(_decision_repository),
    gate_repository: SignalGateRepository = Depends(_gate_repository),
) -> dict:
    evaluation, _observations = evaluate_and_persist_gate(
        alert_repository, decision_repository, gate_repository, timeframe=timeframe
    )
    return {
        **evaluation.__dict__,
        "decision": evaluation.decision.value,
        "criteria": SIGNAL_GATE_V1_CRITERIA.__dict__,
    }


@router.get("/gate/history")
def get_gate_history(
    gate_version: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    gate_repository: SignalGateRepository = Depends(_gate_repository),
) -> list[dict]:
    return gate_repository.list_gate_results(gate_version=gate_version or SIGNAL_GATE_VERSION, limit=limit)


@router.get("/observations")
def get_observations(
    symbol: Optional[str] = Query(default=None),
    setup_type: Optional[str] = Query(default=None),
    direction: Optional[str] = Query(default=None),
    timeframe: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    resolved_only: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=5000),
    alert_repository: AlertRepository = Depends(_alert_repository),
    decision_repository: DecisionEngineRepository = Depends(_decision_repository),
) -> list[dict]:
    observations = build_prospective_dataset(
        alert_repository, decision_repository, resolved_only=resolved_only
    )
    filtered = [
        o
        for o in observations
        if (symbol is None or o.symbol == symbol)
        and (setup_type is None or o.setup_type == setup_type)
        and (direction is None or o.direction == direction)
        and (timeframe is None or o.timeframe == timeframe)
        and (event_type is None or o.event_type == event_type)
    ]
    return [o.model_dump(mode="json") for o in filtered[:limit]]


@router.get("/cohorts")
def get_cohort(
    event_type: str = Query(...),
    horizon_bars: int = Query(default=5),
    timeframe: Timeframe = Query(default=Timeframe.ONE_HOUR),
    symbol: Optional[str] = Query(default=None),
    setup_type: Optional[str] = Query(default=None),
    direction: Optional[str] = Query(default=None),
    alert_repository: AlertRepository = Depends(_alert_repository),
    decision_repository: DecisionEngineRepository = Depends(_decision_repository),
) -> dict:
    observations = build_prospective_dataset(alert_repository, decision_repository)
    filtered = [
        o
        for o in observations
        if o.event_type == event_type
        and (symbol is None or o.symbol == symbol)
        and (setup_type is None or o.setup_type == setup_type)
        and (direction is None or o.direction == direction)
    ]
    stats = build_cohort_statistics(event_type, filtered, horizon_bars, timeframe)
    return stats.model_dump(mode="json")


@router.get("/summary")
def get_summary(
    timeframe: Timeframe = Query(default=Timeframe.ONE_HOUR),
    horizon_bars: int = Query(default=5),
    alert_repository: AlertRepository = Depends(_alert_repository),
    decision_repository: DecisionEngineRepository = Depends(_decision_repository),
    gate_repository: SignalGateRepository = Depends(_gate_repository),
) -> dict:
    summary = build_summary(
        alert_repository, decision_repository, gate_repository, timeframe=timeframe, horizon_bars=horizon_bars
    )
    return summary.model_dump(mode="json")


@router.get("/historical-comparison")
def get_historical_comparison(
    symbol: str = Query(...),
    setup_type: str = Query(...),
    direction: str = Query(...),
    horizon_bars: int = Query(default=5),
    alert_repository: AlertRepository = Depends(_alert_repository),
    decision_repository: DecisionEngineRepository = Depends(_decision_repository),
    research_repository: ResearchRepository = Depends(_research_repository),
) -> dict:
    observations = build_prospective_dataset(alert_repository, decision_repository)
    prospective = [
        o
        for o in observations
        if o.symbol == symbol and o.setup_type == setup_type and o.direction == direction
    ]
    historical_returns = historical_returns_for_cohort(
        research_repository,
        symbol=symbol,
        setup_type=setup_type,
        direction=direction,
        horizon_bars=horizon_bars,
    )
    comparison = compare_historical_vs_prospective(
        f"{symbol}:{setup_type}:{direction}", historical_returns, prospective, horizon_bars
    )
    return comparison.model_dump(mode="json")
