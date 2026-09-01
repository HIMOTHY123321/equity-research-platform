"""Phase 11 (#L): AI Research Analyst API surface. Thin orchestration only
-- app.ai_analysis.evidence_packet.build_evidence_packet and
app.ai_analysis.brief.generate_research_brief do all the real work, exactly
the "no detection/statistics logic lives in a route" convention
app.api.routes.market.get_setups already documents.

Every generated packet/brief is bound to an explicit `as_of` (#L closing
requirement) -- `as_of` defaults to "now" but a caller may pass a historical
value, which is what tests/unit/ai_analysis/test_evidence_packet_determinism
.py exercises.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai_analysis.brief import generate_research_brief
from app.ai_analysis.evidence_packet import SetupNotFoundError, build_evidence_packet
from app.ai_analysis.provider import AIAnalysisProvider
from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.ai_analysis.research_brief import AnalysisMode, ResearchBrief
from app.ai_analysis.schemas import EvidencePacket
from app.api.deps import get_ai_analysis_provider, get_market_data_provider, get_news_provider
from app.api.routes.market import _validated_symbol, _validated_timeframe
from app.database.session import get_db
from app.market_data.provider import MarketDataProvider
from app.news.provider import NewsProvider
from app.news.repository import SqlAlchemyNewsRepository
from app.research.repository import SqlAlchemyResearchRepository

router = APIRouter(prefix="/api/analysis", tags=["ai-analysis"])


def _news_repository(db: Session = Depends(get_db)) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(db)


def _research_repository(db: Session = Depends(get_db)) -> SqlAlchemyResearchRepository:
    return SqlAlchemyResearchRepository(db)


def _evidence_repository(db: Session = Depends(get_db)) -> SqlAlchemyEvidenceRepository:
    return SqlAlchemyEvidenceRepository(db)


@router.get("/{symbol}/evidence", response_model=EvidencePacket)
def get_evidence_packet(
    symbol: str,
    timeframe: str = Query("1h"),
    setup_id: Optional[str] = Query(None),
    as_of: Optional[datetime] = Query(None),
    market_provider: MarketDataProvider = Depends(get_market_data_provider),
    news_provider: NewsProvider = Depends(get_news_provider),
    news_repository: SqlAlchemyNewsRepository = Depends(_news_repository),
    research_repository: SqlAlchemyResearchRepository = Depends(_research_repository),
    evidence_repository: SqlAlchemyEvidenceRepository = Depends(_evidence_repository),
) -> EvidencePacket:
    validated_symbol = _validated_symbol(symbol)
    validated_timeframe = _validated_timeframe(timeframe)
    try:
        packet = build_evidence_packet(
            symbol=validated_symbol,
            timeframe=validated_timeframe,
            market_provider=market_provider,
            news_provider=news_provider,
            news_repository=news_repository,
            research_repository=research_repository,
            setup_id=setup_id,
            as_of=as_of,
        )
    except SetupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    evidence_repository.save_packet(packet)
    return packet


@router.post("/{symbol}/brief", response_model=ResearchBrief)
def create_research_brief(
    symbol: str,
    timeframe: str = Query("1h"),
    setup_id: Optional[str] = Query(None),
    as_of: Optional[datetime] = Query(None),
    mode: AnalysisMode = Query(AnalysisMode.FULL),
    market_provider: MarketDataProvider = Depends(get_market_data_provider),
    news_provider: NewsProvider = Depends(get_news_provider),
    news_repository: SqlAlchemyNewsRepository = Depends(_news_repository),
    research_repository: SqlAlchemyResearchRepository = Depends(_research_repository),
    evidence_repository: SqlAlchemyEvidenceRepository = Depends(_evidence_repository),
    ai_provider: AIAnalysisProvider = Depends(get_ai_analysis_provider),
) -> ResearchBrief:
    validated_symbol = _validated_symbol(symbol)
    validated_timeframe = _validated_timeframe(timeframe)
    try:
        packet = build_evidence_packet(
            symbol=validated_symbol,
            timeframe=validated_timeframe,
            market_provider=market_provider,
            news_provider=news_provider,
            news_repository=news_repository,
            research_repository=research_repository,
            setup_id=setup_id,
            as_of=as_of,
        )
    except SetupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    evidence_repository.save_packet(packet)
    brief, _claims = generate_research_brief(packet, ai_provider, mode)
    evidence_repository.save_brief(brief)
    return brief


@router.get("/{symbol}/brief/{brief_id}", response_model=ResearchBrief)
def get_research_brief(
    symbol: str,
    brief_id: str,
    evidence_repository: SqlAlchemyEvidenceRepository = Depends(_evidence_repository),
) -> ResearchBrief:
    _validated_symbol(symbol)
    brief = evidence_repository.get_brief(brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail=f"Research brief {brief_id!r} not found")
    return brief
