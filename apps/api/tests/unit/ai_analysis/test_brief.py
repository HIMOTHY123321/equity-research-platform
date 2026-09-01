"""Phase 11 (#C/#D): app.ai_analysis.brief.generate_research_brief must
degrade to a deterministic-only brief whenever a provider is unavailable OR
its output fails grounding -- never propagate a provider failure as a
request failure, and never serve ungrounded content."""

from __future__ import annotations

from datetime import datetime, timezone

from app.ai_analysis.brief import generate_research_brief
from app.ai_analysis.evidence_packet import build_evidence_packet
from app.ai_analysis.provider import AIAnalysisProvider, AIAnalysisUnavailableError
from app.ai_analysis.research_brief import AnalysisMode, ResearchBrief
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1H, FakeMarketDataProvider, make_repositories, make_session


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
        as_of=SPY_1H[-1].timestamp,
    )


class _UnavailableProvider(AIAnalysisProvider):
    name = "unavailable"

    def explain_setup(self, packet, claims):
        raise AIAnalysisUnavailableError("no credentials")

    def summarize_contradictions(self, packet, claims):
        raise AIAnalysisUnavailableError("no credentials")

    def generate_monitoring_summary(self, packet, claims):
        raise AIAnalysisUnavailableError("no credentials")

    def synthesize_research_brief(self, packet, claims, mode):
        raise AIAnalysisUnavailableError("no credentials")


class _HallucinatingProvider(AIAnalysisProvider):
    name = "hallucinating"

    def explain_setup(self, packet, claims):
        return "STRONG BUY"

    def summarize_contradictions(self, packet, claims):
        return "n/a"

    def generate_monitoring_summary(self, packet, claims):
        return ["n/a"]

    def synthesize_research_brief(self, packet, claims, mode):
        return ResearchBrief(
            brief_id="bad-brief",
            evidence_packet_id=packet.packet_id,
            mode=mode,
            setup_explanation="STRONG BUY, 99% chance of a breakout.",
            generated_at=datetime.now(timezone.utc),
            as_of=packet.as_of,
            provider=self.name,
        )


class _EchoProvider(AIAnalysisProvider):
    """Returns a trivially grounded brief (claim statements verbatim) --
    used to prove a well-behaved provider's output passes through
    unmodified."""

    name = "echo"

    def explain_setup(self, packet, claims):
        return "ok"

    def summarize_contradictions(self, packet, claims):
        return "ok"

    def generate_monitoring_summary(self, packet, claims):
        return []

    def synthesize_research_brief(self, packet, claims, mode):
        return ResearchBrief(
            brief_id="good-brief",
            evidence_packet_id=packet.packet_id,
            mode=mode,
            situation_summary="Grounded summary with no invented facts.",
            generated_at=datetime.now(timezone.utc),
            as_of=packet.as_of,
            provider=self.name,
        )


def test_unavailable_provider_falls_back_to_deterministic_brief():
    packet = _packet()
    brief, claims = generate_research_brief(packet, _UnavailableProvider(), AnalysisMode.FULL)
    assert brief.provider == "deterministic-fallback"
    assert brief.grounding_rejected is False
    assert isinstance(claims, list)


def test_hallucinating_provider_output_is_rejected_and_replaced():
    packet = _packet()
    brief, _claims = generate_research_brief(packet, _HallucinatingProvider(), AnalysisMode.FULL)
    assert brief.provider == "deterministic-fallback"
    assert brief.grounding_rejected is True
    assert brief.grounding_violations
    text = brief.setup_explanation.lower()
    assert "buy" not in text and "99%" not in text


def test_well_behaved_provider_output_passes_through():
    packet = _packet()
    brief, _claims = generate_research_brief(packet, _EchoProvider(), AnalysisMode.FULL)
    assert brief.provider == "echo"
    assert brief.grounding_rejected is False
    assert brief.situation_summary == "Grounded summary with no invented facts."
