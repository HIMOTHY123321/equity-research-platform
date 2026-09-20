"""Shared fixtures for tests/unit/forecasting -- same real-candle-fixture +
in-memory-SQLite pattern as tests/unit/ai_analysis, extended with an
actually-persisted Phase 7 research run (via execute_research_run, same
helper test_evidence_packet_determinism.py uses) so evidence-quality-
dependent tests exercise real Phase 8/9 statistics rather than a hand-built
stand-in.

`CREATION_AS_OF` is deliberately the midpoint of the fixture, not the last
candle: it leaves a full trailing half of the fixture available as genuine
"future" data for resolver tests, while the seeded research run's own
`end_date` is pinned at or before `CREATION_AS_OF` so historical_research is
actually populated on a packet built at that instant.
"""

from __future__ import annotations

from datetime import datetime

from app.ai_analysis.evidence_packet import build_evidence_packet
from app.ai_analysis.market_snapshot import build_market_snapshot
from app.ai_analysis.schemas import EvidencePacket
from app.news.fixture_provider import FixtureNewsProvider
from app.news.repository import SqlAlchemyNewsRepository
from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.engine import execute_research_run
from app.research.repository import SqlAlchemyResearchRepository
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import (
    SPY_1D,
    SPY_1H,
    FakeMarketDataProvider,
    make_repositories,
    make_session,
)

CREATION_AS_OF = SPY_1H[len(SPY_1H) // 2].timestamp


def seeded_repositories() -> tuple[SqlAlchemyResearchRepository, SqlAlchemyNewsRepository]:
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    execute_research_run(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        start_date=SPY_1H[0].timestamp,
        end_date=CREATION_AS_OF,
        primary_candles=SPY_1H,
        daily_candles=SPY_1D,
        four_hour_candles=SPY_1H,
        provider_name="fixture",
        repository=research_repository,
        research_config=DEFAULT_RESEARCH_CONFIG,
    )
    return research_repository, news_repository


def some_candidate_id(as_of: datetime = CREATION_AS_OF) -> str:
    provider = FakeMarketDataProvider()
    snapshot = build_market_snapshot("SPY", Timeframe.ONE_HOUR, provider, as_of)
    pool = (
        snapshot.setup_snapshot.qualified_setups
        + snapshot.setup_snapshot.candidates
        + snapshot.setup_snapshot.rejected_candidates
    )
    assert pool, "fixture must produce at least one candidate to test against"
    return pool[0].id


def build_packet(
    setup_id: str | None = None,
    as_of: datetime = CREATION_AS_OF,
    research_repository=None,
    news_repository=None,
) -> EvidencePacket:
    if research_repository is None or news_repository is None:
        research_repository, news_repository = seeded_repositories()
    return build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        setup_id=setup_id,
        as_of=as_of,
    )
