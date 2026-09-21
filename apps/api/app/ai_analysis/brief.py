"""Phase 11 (#D): the one place a ResearchBrief is produced. Derives
EvidenceClaims, asks the configured provider to synthesize a brief, and
independently re-validates the result (app.ai_analysis.validation) before
it is ever returned or persisted. A provider outage or a failed grounding
check both fall back to the same thing: a brief assembled directly from the
deterministic claims, with no AI text at all -- the product never fails,
it just narrows to "deterministic evidence only" (#C).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from app.ai_analysis.claims import ClaimDirection, EvidenceClaim, derive_evidence_claims
from app.ai_analysis.provider import AIAnalysisProvider, AIAnalysisUnavailableError
from app.ai_analysis.research_brief import RESEARCH_BRIEF_PROMPT_VERSION, AnalysisMode, ResearchBrief
from app.ai_analysis.schemas import EvidencePacket
from app.ai_analysis.validation import validate_research_brief


def _fallback_brief_id(packet_id: str, mode: AnalysisMode) -> str:
    digest_source = f"{packet_id}|{mode.value}|fallback"
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]


def build_deterministic_fallback_brief(
    packet: EvidencePacket,
    claims: list[EvidenceClaim],
    mode: AnalysisMode,
    violations: Optional[list[str]] = None,
) -> ResearchBrief:
    """Every field here is either a claim statement (already deterministic,
    see app.ai_analysis.claims) or a direct packet field -- guaranteed to
    pass app.ai_analysis.validation, and used whenever a provider is
    unavailable or its output failed grounding.

    Hardening pass (§U): mode still selects which slice of this same
    deterministic content is surfaced -- the fallback path must not
    silently ignore mode just because it's already the safety net."""
    supporting = [c.statement for c in claims if c.direction == ClaimDirection.SUPPORTING]
    contradicting = [c.statement for c in claims if c.direction == ClaimDirection.CONTRADICTING]
    unknown = [c.statement for c in claims if c.direction == ClaimDirection.UNKNOWN]
    refs = sorted({ref for c in claims for ref in c.evidence_refs})
    invalidation = list(packet.setup.candidate.invalidation_criteria) if packet.setup is not None else []

    situation_summary = f"{packet.symbol} ({packet.timeframe}). RANKING GATE: {packet.ranking_gate_status}."
    setup_explanation = "; ".join(supporting) or "No supporting deterministic claims are currently available."
    catalyst_text = (
        packet.catalyst_context.label_basis
        if packet.catalyst_context is not None
        else "No catalyst context available."
    )
    # (§Y) See mock_provider.py's matching comment -- formal statistical
    # research and historical analog search are independent systems.
    historical_text = (
        packet.historical_research.independence.evidence_maturity_basis
        if packet.historical_research is not None
        else "Formal statistical research is unavailable for this packet's as_of. This does not imply "
        "historical analog search is unavailable -- see the separate Historical Analogs section."
    )

    if mode == AnalysisMode.QUICK:
        fields = dict(
            setup_explanation="",
            supporting_evidence=supporting[:1],
            contradictory_evidence=contradicting[:1],
            catalyst_context="",
            historical_context="",
            uncertainty=[],
            invalidation_conditions=invalidation[:1],
            monitor_next=[],
        )
    elif mode == AnalysisMode.CATALYST:
        fields = dict(
            setup_explanation="",
            supporting_evidence=[],
            contradictory_evidence=[],
            catalyst_context=catalyst_text,
            historical_context="",
            uncertainty=[],
            invalidation_conditions=[],
            monitor_next=[],
        )
    elif mode == AnalysisMode.ANALOGS:
        fields = dict(
            setup_explanation="",
            supporting_evidence=[],
            contradictory_evidence=[],
            catalyst_context="",
            historical_context=historical_text,
            uncertainty=[],
            invalidation_conditions=[],
            monitor_next=[],
        )
    elif mode == AnalysisMode.WHY_THIS_SETUP:
        section = packet.setup
        fields = dict(
            setup_explanation=setup_explanation,
            supporting_evidence=section.qualification_reasons if section is not None else [],
            contradictory_evidence=section.conflict_reasons if section is not None else [],
            catalyst_context="",
            historical_context="",
            uncertainty=section.near_miss_reasons if section is not None else [],
            invalidation_conditions=invalidation,
            monitor_next=[],
        )
    elif mode == AnalysisMode.WHY_NOT:
        section = packet.setup
        fields = dict(
            setup_explanation="This candidate did not qualify."
            if section is not None and not section.qualified
            else "This candidate qualified; no rejected alternative to explain.",
            supporting_evidence=[],
            contradictory_evidence=(section.rejection_reasons or section.conflict_reasons)
            if section is not None
            else [],
            catalyst_context="",
            historical_context="",
            uncertainty=section.near_miss_reasons if section is not None else [],
            invalidation_conditions=[],
            monitor_next=[],
        )
    else:  # FULL
        fields = dict(
            setup_explanation=setup_explanation,
            supporting_evidence=supporting,
            contradictory_evidence=contradicting,
            catalyst_context=catalyst_text,
            historical_context=historical_text,
            uncertainty=unknown,
            invalidation_conditions=invalidation,
            monitor_next=invalidation,
        )

    return ResearchBrief(
        brief_id=_fallback_brief_id(packet.packet_id, mode),
        evidence_packet_id=packet.packet_id,
        mode=mode,
        situation_summary=situation_summary,
        evidence_refs=refs,
        generated_at=datetime.now(timezone.utc),
        as_of=packet.as_of,
        provider="deterministic-fallback",
        model=None,
        prompt_version=RESEARCH_BRIEF_PROMPT_VERSION,
        grounding_rejected=bool(violations),
        grounding_violations=violations or [],
        **fields,
    )


def generate_research_brief(
    packet: EvidencePacket,
    provider: AIAnalysisProvider,
    mode: AnalysisMode = AnalysisMode.FULL,
) -> tuple[ResearchBrief, list[EvidenceClaim]]:
    claims = derive_evidence_claims(packet)

    try:
        raw_brief = provider.synthesize_research_brief(packet, claims, mode)
    except AIAnalysisUnavailableError:
        return build_deterministic_fallback_brief(packet, claims, mode), claims

    result = validate_research_brief(raw_brief, packet, claims)
    if not result.is_valid:
        violations = [f"{v.code}: {v.detail}" for v in result.violations]
        return build_deterministic_fallback_brief(packet, claims, mode, violations), claims

    return raw_brief, claims
