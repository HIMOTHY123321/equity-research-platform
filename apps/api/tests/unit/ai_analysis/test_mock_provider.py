"""Phase 11 (#C): the mock provider is the product's default and every
test's dependency -- its output must always pass its own grounding
validator, for every explanation mode, with or without a targeted setup.
"""

from __future__ import annotations

import pytest

from app.ai_analysis.claims import derive_evidence_claims
from app.ai_analysis.evidence_packet import build_evidence_packet
from app.ai_analysis.market_snapshot import build_market_snapshot
from app.ai_analysis.mock_provider import MockAIAnalysisProvider
from app.ai_analysis.research_brief import AnalysisMode
from app.ai_analysis.validation import validate_research_brief
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import FakeMarketDataProvider, make_repositories, make_session
from tests.unit.news.conftest import raw_article


def _as_of():
    from tests.unit.ai_analysis.conftest import SPY_1H

    return SPY_1H[-1].timestamp


def _setup_id():
    provider = FakeMarketDataProvider()
    market_snapshot = build_market_snapshot("SPY", Timeframe.ONE_HOUR, provider, _as_of())
    snapshot = market_snapshot.setup_snapshot
    pool = snapshot.qualified_setups + snapshot.candidates + snapshot.rejected_candidates
    return pool[0].id if pool else None


def _packet(setup_id=None, with_news=False):
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    articles = (
        [raw_article("Acme reports quarterly earnings beat", _as_of(), ["SPY"], source="Reuters")]
        if with_news
        else []
    )
    return build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider(articles),
        news_repository=news_repository,
        research_repository=research_repository,
        setup_id=setup_id,
        as_of=_as_of(),
    )


@pytest.mark.parametrize("mode", list(AnalysisMode))
def test_mock_brief_passes_its_own_grounding_validation_symbol_level(mode):
    packet = _packet(with_news=True)
    claims = derive_evidence_claims(packet)
    brief = MockAIAnalysisProvider().synthesize_research_brief(packet, claims, mode)
    result = validate_research_brief(brief, packet, claims)
    assert result.is_valid, result.violations


@pytest.mark.parametrize("mode", list(AnalysisMode))
def test_mock_brief_passes_its_own_grounding_validation_setup_scoped(mode):
    setup_id = _setup_id()
    if setup_id is None:
        pytest.skip("fixture produced no candidates to scope a setup-level packet to")
    packet = _packet(setup_id=setup_id, with_news=True)
    claims = derive_evidence_claims(packet)
    brief = MockAIAnalysisProvider().synthesize_research_brief(packet, claims, mode)
    result = validate_research_brief(brief, packet, claims)
    assert result.is_valid, result.violations


def test_mock_brief_is_deterministic():
    packet = _packet(with_news=True)
    claims = derive_evidence_claims(packet)
    provider = MockAIAnalysisProvider()
    first = provider.synthesize_research_brief(packet, claims, AnalysisMode.FULL)
    second = provider.synthesize_research_brief(packet, claims, AnalysisMode.FULL)
    assert first.model_dump(exclude={"generated_at"}) == second.model_dump(exclude={"generated_at"})


def test_all_six_modes_produce_materially_different_content():
    # Hardening pass (§U) regression: QUICK/FULL/WHY_THIS_SETUP/WHY_NOT/
    # CATALYST/ANALOGS used to render byte-identical content -- only
    # `mode`/`brief_id` differed. Every mode must now select a genuinely
    # different slice of the same underlying packet/claims.
    setup_id = _setup_id()
    packet = _packet(setup_id=setup_id, with_news=True)
    claims = derive_evidence_claims(packet)
    provider = MockAIAnalysisProvider()

    def _content_signature(brief):
        return (
            brief.setup_explanation,
            tuple(brief.supporting_evidence),
            tuple(brief.contradictory_evidence),
            brief.catalyst_context,
            brief.historical_context,
            tuple(brief.uncertainty),
            tuple(brief.invalidation_conditions),
        )

    signatures = {
        mode: _content_signature(provider.synthesize_research_brief(packet, claims, mode))
        for mode in AnalysisMode
    }
    # No two modes should produce the exact same content signature.
    assert len(set(signatures.values())) == len(signatures), signatures


def test_quick_mode_is_concise():
    packet = _packet(with_news=True)
    claims = derive_evidence_claims(packet)
    brief = MockAIAnalysisProvider().synthesize_research_brief(packet, claims, AnalysisMode.QUICK)
    assert len(brief.supporting_evidence) <= 1
    assert len(brief.contradictory_evidence) <= 1
    assert brief.catalyst_context == ""
    assert brief.historical_context == ""


def test_mock_brief_never_contains_banned_language():
    packet = _packet(with_news=True)
    claims = derive_evidence_claims(packet)
    brief = MockAIAnalysisProvider().synthesize_research_brief(packet, claims, AnalysisMode.FULL)
    text = " ".join(
        [brief.situation_summary, brief.setup_explanation, brief.catalyst_context, brief.historical_context]
        + brief.supporting_evidence
        + brief.contradictory_evidence
    ).lower()
    for banned in ("buy", "sell", "guarantee", "probability of", "chance"):
        assert banned not in text
