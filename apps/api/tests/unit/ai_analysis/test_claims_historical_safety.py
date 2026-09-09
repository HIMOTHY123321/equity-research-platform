"""Phase 11.1 (#G): no EvidenceClaim may refer to evidence unavailable at
`packet.as_of`, and every claim's evidence_refs must resolve only to
evidence actually contained in that same packet -- never to something a
future article/research snapshot introduced after the fact.
"""

from __future__ import annotations

from datetime import timedelta

from app.ai_analysis.claims import derive_evidence_claims
from app.ai_analysis.evidence_packet import build_evidence_packet
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1H, FakeMarketDataProvider, make_repositories, make_session
from tests.unit.news.conftest import raw_article

_AS_OF = SPY_1H[-1].timestamp


def _packet(articles):
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    return build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider(articles),
        news_repository=news_repository,
        research_repository=research_repository,
        as_of=_AS_OF,
    )


def _known_evidence_refs(packet) -> set[str]:
    """Every ref value a claim is legally allowed to cite, derived
    independently from claim-derivation logic itself (reading straight off
    packet fields) so this is a real cross-check, not a tautology."""
    refs: set[str] = set()
    if packet.support_resistance.nearest_support is not None:
        refs.add(f"zone:{packet.support_resistance.nearest_support.id}")
    if packet.support_resistance.nearest_resistance is not None:
        refs.add(f"zone:{packet.support_resistance.nearest_resistance.id}")
    refs.add("structure:breaks_of_structure")
    refs.add("structure:changes_of_character")
    if packet.setup is not None:
        refs.add(f"setup:{packet.setup.candidate.id}")
    if packet.provenance.research_run_ids:
        refs.add(f"research:{','.join(packet.provenance.research_run_ids)}")
    if packet.catalyst_context is not None:
        refs.add("catalyst:none")
        if packet.catalyst_context.nearest_catalyst is not None:
            refs.add(f"catalyst:{packet.catalyst_context.nearest_catalyst.event_id}")
    if packet.historical_analogs is not None:
        for analog in packet.historical_analogs.analogs:
            refs.add(f"analog:{analog.setup_id}")
    return refs


def test_claims_are_identical_when_a_dramatic_future_article_is_appended():
    past_article = raw_article(
        "Acme reports quarterly earnings beat", _AS_OF - timedelta(hours=2), ["SPY"], source="Reuters"
    )
    future_article = raw_article(
        "BREAKING: Acme collapses 90 percent on fraud allegations",
        _AS_OF + timedelta(hours=2),
        ["SPY"],
        source="Reuters",
    )

    baseline = _packet([past_article])
    adversarial = _packet([past_article, future_article])

    baseline_claims = derive_evidence_claims(baseline)
    adversarial_claims = derive_evidence_claims(adversarial)

    assert [c.model_dump() for c in baseline_claims] == [c.model_dump() for c in adversarial_claims]

    all_text = " ".join(c.statement for c in adversarial_claims).lower()
    assert "collapse" not in all_text
    assert "fraud" not in all_text
    assert "90 percent" not in all_text


def test_every_claim_evidence_ref_resolves_within_the_packet():
    past_article = raw_article(
        "Acme reports quarterly earnings beat", _AS_OF - timedelta(hours=2), ["SPY"], source="Reuters"
    )
    packet = _packet([past_article])
    claims = derive_evidence_claims(packet)
    known = _known_evidence_refs(packet)

    for claim in claims:
        for ref in claim.evidence_refs:
            assert ref in known, f"claim {claim.claim_type!r} cites unresolvable ref {ref!r}"
