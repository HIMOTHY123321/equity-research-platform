"""Phase 11 (#C): the deterministic provider every test runs against, and
the default in every environment with no AI credentials configured. Builds
prose entirely by templating over EvidenceClaims/EvidencePacket fields --
never a model call, never randomness -- so its output is trivially grounded
(app.ai_analysis.validation will never reject it) and byte-identical given
the same packet+claims.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.ai_analysis.claims import ClaimDirection, EvidenceClaim
from app.ai_analysis.provider import AIAnalysisProvider
from app.ai_analysis.research_brief import RESEARCH_BRIEF_PROMPT_VERSION, AnalysisMode, ResearchBrief
from app.ai_analysis.schemas import EvidencePacket


def _claims_by_direction(claims: list[EvidenceClaim], direction: ClaimDirection) -> list[EvidenceClaim]:
    return [c for c in claims if c.direction == direction]


def _brief_id(packet_id: str, mode: AnalysisMode) -> str:
    digest_source = f"{packet_id}|{mode.value}|{RESEARCH_BRIEF_PROMPT_VERSION}"
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]


class MockAIAnalysisProvider(AIAnalysisProvider):
    name = "mock"

    def explain_setup(self, packet: EvidencePacket, claims: list[EvidenceClaim]) -> str:
        if packet.setup is None:
            return (
                f"No specific setup is targeted; this is a symbol-level evidence review for "
                f"{packet.symbol}."
            )
        setup_type = packet.setup.candidate.setup_type.value
        supporting = _claims_by_direction(claims, ClaimDirection.SUPPORTING)
        if not supporting:
            return (
                f"{packet.symbol} {setup_type} candidate detected; "
                "no supporting deterministic claims are currently available."
            )
        sentences = "; ".join(c.statement for c in supporting[:5])
        return f"{packet.symbol} {setup_type} candidate detected because: {sentences}."

    def summarize_contradictions(self, packet: EvidencePacket, claims: list[EvidenceClaim]) -> str:
        contradicting = _claims_by_direction(claims, ClaimDirection.CONTRADICTING)
        unknown = _claims_by_direction(claims, ClaimDirection.UNKNOWN)
        if not contradicting and not unknown:
            return "No contradicting or unresolved evidence was identified in the current evidence packet."
        parts = [c.statement for c in contradicting[:5]] + [c.statement for c in unknown[:3]]
        return "What the evidence does not prove: " + "; ".join(parts) + "."

    def generate_monitoring_summary(self, packet: EvidencePacket, claims: list[EvidenceClaim]) -> list[str]:
        if packet.setup is None or not packet.setup.candidate.invalidation_criteria:
            return ["No deterministic invalidation criteria are available for this evidence packet."]
        return list(packet.setup.candidate.invalidation_criteria)

    def synthesize_research_brief(
        self, packet: EvidencePacket, claims: list[EvidenceClaim], mode: AnalysisMode
    ) -> ResearchBrief:
        supporting = [c.statement for c in _claims_by_direction(claims, ClaimDirection.SUPPORTING)]
        contradicting = [c.statement for c in _claims_by_direction(claims, ClaimDirection.CONTRADICTING)]
        unknown = [c.statement for c in _claims_by_direction(claims, ClaimDirection.UNKNOWN)]
        refs = sorted({ref for c in claims for ref in c.evidence_refs})

        situation_summary = (
            f"{packet.symbol} ({packet.timeframe}) as of {packet.as_of.isoformat()}. "
            f"RANKING GATE: {packet.ranking_gate_status}."
        )
        catalyst_text = (
            packet.catalyst_context.label_basis
            if packet.catalyst_context is not None
            else "No catalyst context available."
        )
        historical_text = (
            packet.historical_research.independence.evidence_maturity_basis
            if packet.historical_research is not None
            else "No historical research runs are available for this symbol/timeframe."
        )

        return ResearchBrief(
            brief_id=_brief_id(packet.packet_id, mode),
            evidence_packet_id=packet.packet_id,
            mode=mode,
            situation_summary=situation_summary,
            setup_explanation=self.explain_setup(packet, claims),
            supporting_evidence=supporting,
            contradictory_evidence=contradicting,
            catalyst_context=catalyst_text,
            historical_context=historical_text,
            uncertainty=unknown,
            invalidation_conditions=self.generate_monitoring_summary(packet, claims),
            monitor_next=self.generate_monitoring_summary(packet, claims),
            evidence_refs=refs,
            generated_at=datetime.now(timezone.utc),
            as_of=packet.as_of,
            provider=self.name,
            model=None,
            prompt_version=RESEARCH_BRIEF_PROMPT_VERSION,
        )
