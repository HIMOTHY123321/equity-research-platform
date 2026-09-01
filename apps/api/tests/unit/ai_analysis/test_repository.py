"""Phase 11 (#K): EvidencePacket/ResearchBrief persistence -- round-trip
fidelity and idempotent saves on the deterministic business key, same
convention as Phase 10's article/event upsert tests."""

from __future__ import annotations

from app.ai_analysis.brief import generate_research_brief
from app.ai_analysis.evidence_packet import build_evidence_packet
from app.ai_analysis.mock_provider import MockAIAnalysisProvider
from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.ai_analysis.research_brief import AnalysisMode
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1H, FakeMarketDataProvider, make_repositories, make_session


def _packet(research_repository, news_repository):
    return build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        as_of=SPY_1H[-1].timestamp,
    )


def test_save_and_get_packet_round_trips():
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    evidence_repository = SqlAlchemyEvidenceRepository(session)

    packet = _packet(research_repository, news_repository)
    evidence_repository.save_packet(packet)

    fetched = evidence_repository.get_packet(packet.packet_id)
    assert fetched is not None
    assert fetched.packet_id == packet.packet_id
    assert fetched.symbol == packet.symbol


def test_save_packet_is_idempotent():
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    evidence_repository = SqlAlchemyEvidenceRepository(session)

    packet = _packet(research_repository, news_repository)
    first_id = evidence_repository.save_packet(packet)
    second_id = evidence_repository.save_packet(packet)
    assert first_id == second_id


def test_save_and_get_brief_round_trips():
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    evidence_repository = SqlAlchemyEvidenceRepository(session)

    packet = _packet(research_repository, news_repository)
    brief, _claims = generate_research_brief(packet, MockAIAnalysisProvider(), AnalysisMode.QUICK)
    evidence_repository.save_brief(brief)

    fetched = evidence_repository.get_brief(brief.brief_id)
    assert fetched is not None
    assert fetched.brief_id == brief.brief_id
    assert fetched.mode == AnalysisMode.QUICK


def test_list_briefs_for_packet():
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    evidence_repository = SqlAlchemyEvidenceRepository(session)

    packet = _packet(research_repository, news_repository)
    provider = MockAIAnalysisProvider()
    for mode in (AnalysisMode.QUICK, AnalysisMode.FULL):
        brief, _claims = generate_research_brief(packet, provider, mode)
        evidence_repository.save_brief(brief)

    briefs = evidence_repository.list_briefs_for_packet(packet.packet_id)
    assert len(briefs) == 2


def test_get_missing_packet_returns_none():
    session = make_session()
    evidence_repository = SqlAlchemyEvidenceRepository(session)
    assert evidence_repository.get_packet("does-not-exist") is None
