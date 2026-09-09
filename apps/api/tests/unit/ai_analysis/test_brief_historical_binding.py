"""Phase 11.1 (#H): a ResearchBrief must always bind to the exact frozen
EvidencePacket it was generated from, and re-fetching a persisted historical
brief must never recompute it against today's market state -- persistence
is a pure read, full stop.
"""

from __future__ import annotations

from app.ai_analysis.brief import generate_research_brief
from app.ai_analysis.evidence_packet import build_evidence_packet
from app.ai_analysis.mock_provider import MockAIAnalysisProvider
from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.ai_analysis.research_brief import AnalysisMode
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1H, FakeMarketDataProvider, make_repositories, make_session

_AS_OF = SPY_1H[len(SPY_1H) // 2].timestamp


def _historical_packet():
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    return build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        as_of=_AS_OF,
    )


def test_brief_binds_to_its_exact_evidence_packet_id():
    packet = _historical_packet()
    brief, _claims = generate_research_brief(packet, MockAIAnalysisProvider(), AnalysisMode.FULL)
    assert brief.evidence_packet_id == packet.packet_id
    assert brief.as_of == packet.as_of


def test_fetching_a_persisted_historical_brief_never_recomputes_it():
    session = make_session()
    evidence_repository = SqlAlchemyEvidenceRepository(session)

    packet = _historical_packet()
    brief, _claims = generate_research_brief(packet, MockAIAnalysisProvider(), AnalysisMode.FULL)
    evidence_repository.save_packet(packet)
    evidence_repository.save_brief(brief)

    # A brand-new provider fetch (as "today's market data" would be, if this
    # were recomputed) is deliberately never touched here -- get_brief/
    # get_packet take no provider at all, structurally proving the read
    # path cannot recompute anything.
    fetched_brief = evidence_repository.get_brief(brief.brief_id)
    fetched_packet = evidence_repository.get_packet(fetched_brief.evidence_packet_id)

    assert fetched_brief.model_dump() == brief.model_dump()
    assert fetched_packet.model_dump() == packet.model_dump()
    assert fetched_packet.mode.value == "historical_snapshot"


def test_rebuilding_at_the_same_historical_as_of_reproduces_the_same_packet_id():
    """A user re-opening the same historical instant later must land on the
    exact same packet identity -- the deterministic packet_id convention is
    what makes "regenerate" and "look up the existing one" the same
    operation rather than silently drifting."""
    first = _historical_packet()
    second = _historical_packet()
    assert first.packet_id == second.packet_id
    exclude = {"generated_at": True, "provenance": {"generated_at"}}
    assert first.model_dump(exclude=exclude) == second.model_dump(exclude=exclude)
