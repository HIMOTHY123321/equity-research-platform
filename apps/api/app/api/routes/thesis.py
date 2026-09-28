"""Phase 19 (Part 3/Part 12): GET /api/symbols/{symbol}/thesis -- thin
orchestration only, app.thesis.service does all the composition. Never
triggers a new Decision Engine scan (that is POST /api/decisions/{symbol}/
scan's job); this route only reads/composes what already exists, so it is
always safe to call on every page load.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository, SqlAlchemyAlertRepository
from app.api.deps import get_market_data_provider, get_news_provider
from app.config import get_settings
from app.database.session import get_db
from app.decision_engine.repository import DecisionEngineRepository, SqlAlchemyDecisionEngineRepository
from app.market_data.provider import MarketDataProvider
from app.monitoring.universe import MonitoringUniverse
from app.news.provider import NewsProvider
from app.news.repository import SqlAlchemyNewsRepository
from app.research.repository import SqlAlchemyResearchRepository
from app.schemas.market_data import Timeframe
from app.thesis.opportunity_schemas import AttentionCategory, OpportunityListResponse
from app.thesis.opportunity_service import build_opportunities
from app.thesis.schemas import StockThesis
from app.thesis.service import build_stock_thesis
from app.validation.repository import SignalGateRepository, SqlAlchemySignalGateRepository

router = APIRouter(tags=["thesis"])


def _decision_repository(db: Session = Depends(get_db)) -> DecisionEngineRepository:
    return SqlAlchemyDecisionEngineRepository(db)


def _gate_repository(db: Session = Depends(get_db)) -> SignalGateRepository:
    return SqlAlchemySignalGateRepository(db)


def _research_repository(db: Session = Depends(get_db)) -> SqlAlchemyResearchRepository:
    return SqlAlchemyResearchRepository(db)


def _news_repository(db: Session = Depends(get_db)) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(db)


def _alert_repository(db: Session = Depends(get_db)) -> AlertRepository:
    return SqlAlchemyAlertRepository(db)


def _monitoring_universe(
    alert_repository: AlertRepository = Depends(_alert_repository),
) -> MonitoringUniverse:
    return MonitoringUniverse(alert_repository)


@router.get("/api/symbols/{symbol}/thesis", response_model=StockThesis)
def get_stock_thesis(
    symbol: str,
    timeframe: Timeframe = Query(default=Timeframe.ONE_HOUR),
    as_of: Optional[datetime] = Query(
        default=None,
        description="Anti-lookahead point-in-time cutoff. Omit for the current, live thesis.",
    ),
    market_provider: MarketDataProvider = Depends(get_market_data_provider),
    news_provider: NewsProvider = Depends(get_news_provider),
    news_repository: SqlAlchemyNewsRepository = Depends(_news_repository),
    research_repository: SqlAlchemyResearchRepository = Depends(_research_repository),
    decision_repository: DecisionEngineRepository = Depends(_decision_repository),
    gate_repository: SignalGateRepository = Depends(_gate_repository),
) -> StockThesis:
    resolved_as_of = as_of
    if resolved_as_of is not None and resolved_as_of.tzinfo is None:
        resolved_as_of = resolved_as_of.replace(tzinfo=timezone.utc)
    if resolved_as_of is not None and resolved_as_of > datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="as_of may not be in the future")

    return build_stock_thesis(
        symbol=symbol.upper(),
        timeframe=timeframe,
        market_provider=market_provider,
        news_provider=news_provider,
        news_repository=news_repository,
        research_repository=research_repository,
        decision_repository=decision_repository,
        gate_repository=gate_repository,
        as_of=resolved_as_of,
    )


@router.get("/api/opportunities", response_model=OpportunityListResponse)
def get_opportunities(
    timeframe: Timeframe = Query(default=Timeframe.ONE_HOUR),
    category: Optional[AttentionCategory] = Query(default=None),
    setup_type: Optional[str] = Query(default=None),
    sort: str = Query(default="state", pattern="^(state|symbol|recency)$"),
    market_provider: MarketDataProvider = Depends(get_market_data_provider),
    universe: MonitoringUniverse = Depends(_monitoring_universe),
    decision_repository: DecisionEngineRepository = Depends(_decision_repository),
    gate_repository: SignalGateRepository = Depends(_gate_repository),
) -> OpportunityListResponse:
    return build_opportunities(
        timeframe=timeframe,
        market_provider=market_provider,
        universe=universe,
        decision_repository=decision_repository,
        gate_repository=gate_repository,
        provider_name=get_settings().market_data_provider,
        category=category,
        setup_type=setup_type,
        sort=sort,
    )
