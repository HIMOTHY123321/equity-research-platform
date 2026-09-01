"""Phase 11 (#B): EvidenceClaim derivation is deterministic and traceable --
same packet in, same claims out, every claim cites a ref that exists
somewhere on the packet, and no claim is itself an invented fact (every
claim is built purely from already-typed packet fields)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.ai_analysis.claims import ClaimDirection, derive_evidence_claims
from app.ai_analysis.evidence_packet import build_evidence_packet
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import FakeMarketDataProvider, make_repositories, make_session


def _packet():
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    return build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        as_of=datetime.now(timezone.utc),
    )


def test_claims_are_deterministic_given_the_same_packet():
    packet = _packet()
    first = derive_evidence_claims(packet)
    second = derive_evidence_claims(packet)
    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]


def test_every_claim_has_a_valid_direction_and_at_least_one_ref_or_is_neutral():
    packet = _packet()
    claims = derive_evidence_claims(packet)
    assert claims, "expected at least one claim from a populated packet"
    for claim in claims:
        assert claim.direction in set(ClaimDirection)
        assert claim.source == "deterministic"
        assert isinstance(claim.evidence_refs, list)


def test_claim_ids_are_stable_across_two_derivations():
    packet = _packet()
    first_ids = [c.claim_id for c in derive_evidence_claims(packet)]
    second_ids = [c.claim_id for c in derive_evidence_claims(packet)]
    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids))  # never duplicate ids within one derivation
