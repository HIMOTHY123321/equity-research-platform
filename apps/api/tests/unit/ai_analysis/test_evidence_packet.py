"""Phase 11 (#A): EvidencePacket builder tests -- composition correctness,
not statistics (Phase 8/9 already test those exhaustively). Confirms every
section is populated from the right existing engine/repository, a bad
setup_id is rejected, and a symbol-level (no setup_id) packet still works.
"""

from __future__ import annotations

from datetime import datetime

from app.ai_analysis.evidence_packet import SetupNotFoundError, build_evidence_packet
from app.ai_analysis.market_snapshot import build_market_snapshot
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import FakeMarketDataProvider, make_repositories, make_session


def _some_candidate_id(as_of: datetime) -> str:
    provider = FakeMarketDataProvider()
    snapshot = build_market_snapshot("SPY", Timeframe.ONE_HOUR, provider, as_of)
    setup_snapshot = snapshot.setup_snapshot
    pool = (
        setup_snapshot.qualified_setups + setup_snapshot.candidates + setup_snapshot.rejected_candidates
    )
    assert pool, "fixture must produce at least one candidate to test against"
    return pool[0].id


def _as_of() -> datetime:
    # The fixture's own last candle -- gives the detector the full trailing
    # history it needs to actually produce candidates, same convention
    # tests/integration/test_research_catalysts_routes.py uses.
    from tests.unit.ai_analysis.conftest import SPY_1H

    return SPY_1H[-1].timestamp


def test_symbol_level_packet_has_no_setup_section():
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    packet = build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
    )
    assert packet.setup is None
    assert packet.symbol == "SPY"
    assert packet.timeframe == "1h"
    assert packet.ranking_gate_status == "FAIL"
    assert packet.data_quality.insufficient_history is True  # no research runs persisted


def test_setup_scoped_packet_includes_setup_section():
    as_of = _as_of()
    setup_id = _some_candidate_id(as_of)
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    packet = build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        setup_id=setup_id,
        as_of=as_of,
    )
    assert packet.setup is not None
    assert packet.setup.candidate.id == setup_id


def test_unknown_setup_id_raises_setup_not_found():
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    try:
        build_evidence_packet(
            symbol="SPY",
            timeframe=Timeframe.ONE_HOUR,
            market_provider=FakeMarketDataProvider(),
            news_provider=FixtureNewsProvider([]),
            news_repository=news_repository,
            research_repository=research_repository,
            setup_id="does-not-exist",
        )
        raise AssertionError("expected SetupNotFoundError")
    except SetupNotFoundError:
        pass


def test_packet_id_is_deterministic_for_the_same_inputs():
    as_of = _as_of()
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    kwargs = dict(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        as_of=as_of,
    )
    first = build_evidence_packet(**kwargs)
    second = build_evidence_packet(**kwargs)
    assert first.packet_id == second.packet_id


def test_multi_timeframe_structure_includes_daily_and_four_hour():
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    packet = build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
    )
    assert "1d" in packet.multi_timeframe_structure
    assert "4h" in packet.multi_timeframe_structure
    assert "1h" in packet.multi_timeframe_structure
