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
from app.ai_analysis.timestamps import format_exchange_timestamp as _format_exchange_timestamp


def _claims_by_direction(claims: list[EvidenceClaim], direction: ClaimDirection) -> list[EvidenceClaim]:
    return [c for c in claims if c.direction == direction]


def _brief_id(packet_id: str, mode: AnalysisMode) -> str:
    digest_source = f"{packet_id}|{mode.value}|{RESEARCH_BRIEF_PROMPT_VERSION}"
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]


def _build_quick(*, supporting, contradicting, invalidation, situation_summary, **_kw) -> dict:
    return {
        "situation_summary": situation_summary,
        "setup_explanation": "",
        "supporting_evidence": supporting[:1],
        "contradictory_evidence": contradicting[:1],
        "catalyst_context": "",
        "historical_context": "",
        "uncertainty": [],
        "invalidation_conditions": invalidation[:1],
        "monitor_next": [],
    }


def _build_full(
    *, supporting, contradicting, unknown, invalidation, situation_summary, setup_explanation,
    catalyst_text, historical_text, **_kw
) -> dict:
    return {
        "situation_summary": situation_summary,
        "setup_explanation": setup_explanation,
        "supporting_evidence": supporting,
        "contradictory_evidence": contradicting,
        "catalyst_context": catalyst_text,
        "historical_context": historical_text,
        "uncertainty": unknown,
        "invalidation_conditions": invalidation,
        "monitor_next": invalidation,
    }


def _build_why_this_setup(*, packet, situation_summary, invalidation, **_kw) -> dict:
    section = packet.setup
    if section is None:
        return {
            "situation_summary": situation_summary,
            "setup_explanation": "No specific setup is targeted on this packet -- WHY THIS SETUP "
            "has nothing to qualify.",
            "supporting_evidence": [],
            "contradictory_evidence": [],
            "catalyst_context": "",
            "historical_context": "",
            "uncertainty": [],
            "invalidation_conditions": [],
            "monitor_next": [],
        }
    hard_summary = f"{len(section.candidate.hard_checks)} hard requirement(s) evaluated."
    return {
        "situation_summary": situation_summary,
        "setup_explanation": hard_summary,
        "supporting_evidence": section.qualification_reasons,
        "contradictory_evidence": section.conflict_reasons,
        "catalyst_context": "",
        "historical_context": "",
        "uncertainty": section.near_miss_reasons,
        "invalidation_conditions": invalidation,
        "monitor_next": [],
    }


def _rejected_alternative_sentence(alt) -> str:
    """(#7) '{Setup Type} — rejected / Reason: ... / Observed: X / Required: Y'
    built entirely from the candidate's own EvidenceCheck -- never invented."""
    parts = [f"{alt.setup_type.replace('_', ' ').title()} ({alt.direction}) — rejected"]
    if alt.failed_requirement:
        parts.append(f"Reason: {alt.failed_requirement}")
    if alt.observed_value is not None:
        parts.append(f"Observed: {alt.observed_value:g}")
    if alt.required_value is not None:
        parts.append(f"Required: {alt.required_value:g}")
    if alt.conflict:
        parts.append(f"Conflict: {alt.conflict}")
    return " / ".join(parts)


def _build_why_not(*, packet, situation_summary, **_kw) -> dict:
    section = packet.setup
    rejected_alternatives = section.rejected_alternatives if section is not None else []
    alternative_sentences = [_rejected_alternative_sentence(a) for a in rejected_alternatives]

    if section is None or (
        section.qualified and not section.near_miss_reasons and not rejected_alternatives
    ):
        return {
            "situation_summary": situation_summary,
            "setup_explanation": "This packet has no rejected alternative or near-miss candidate to "
            "explain -- WHY NOT is only meaningful when a candidate failed to qualify. No other "
            "candidate from this detection snapshot was rejected either.",
            "supporting_evidence": [],
            "contradictory_evidence": [],
            "catalyst_context": "",
            "historical_context": "",
            "uncertainty": [],
            "invalidation_conditions": [],
            "monitor_next": [],
        }
    explanation = (
        "This candidate did not qualify."
        if not section.qualified
        else "This candidate qualified, but the following near-misses/conflicts were also observed."
    )
    if not alternative_sentences:
        alternative_sentences = [
            "No other candidate from this detection snapshot was rejected -- nothing to compare against."
        ]
    return {
        "situation_summary": situation_summary,
        "setup_explanation": explanation,
        "supporting_evidence": [],
        "contradictory_evidence": (
            (section.rejection_reasons or section.conflict_reasons) + alternative_sentences
        ),
        "catalyst_context": "",
        "historical_context": "",
        "uncertainty": section.near_miss_reasons,
        "invalidation_conditions": [],
        "monitor_next": [],
    }


def _build_catalyst(*, packet, situation_summary, catalyst_text, **_kw) -> dict:
    nearest = packet.nearest_catalyst_event
    pre_post = ""
    if packet.setup is not None and nearest is not None:
        detection = packet.setup.candidate.candidate_candle_timestamp
        pre_post = (
            "Catalyst occurred BEFORE setup detection (pre-setup evidence)."
            if nearest.primary_timestamp <= detection
            else "Catalyst occurred AFTER setup detection -- context only, not part of the "
            "original setup evidence."
        )
    return {
        "situation_summary": situation_summary,
        "setup_explanation": "",
        "supporting_evidence": [],
        "contradictory_evidence": [],
        "catalyst_context": " ".join(filter(None, [catalyst_text, pre_post])),
        "historical_context": "",
        "uncertainty": [],
        "invalidation_conditions": [],
        "monitor_next": [],
    }


def _build_analogs(*, packet, situation_summary, historical_text, **_kw) -> dict:
    analogs = packet.historical_analogs
    if analogs is None or not analogs.analogs:
        summary = historical_text
    else:
        diversity = analogs.diversity
        summary = (
            f"{diversity.total_analogs} historical analog(s) found across "
            f"{diversity.distinct_episode_count} distinct episode(s) and "
            f"{diversity.distinct_symbol_count} symbol(s). {historical_text}"
        )
        if diversity.warning:
            summary = f"{summary} {diversity.warning}"
    return {
        "situation_summary": situation_summary,
        "setup_explanation": "",
        "supporting_evidence": [],
        "contradictory_evidence": [],
        "catalyst_context": "",
        "historical_context": summary,
        "uncertainty": [],
        "invalidation_conditions": [],
        "monitor_next": [],
    }


_MODE_BUILDERS = {
    AnalysisMode.QUICK: _build_quick,
    AnalysisMode.FULL: _build_full,
    AnalysisMode.WHY_THIS_SETUP: _build_why_this_setup,
    AnalysisMode.WHY_NOT: _build_why_not,
    AnalysisMode.CATALYST: _build_catalyst,
    AnalysisMode.ANALOGS: _build_analogs,
}


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
        """Hardening pass (§U): each mode reads a *different slice* of the
        same frozen packet/claims and leaves the rest of the schema's
        optional fields empty (the panel's TextBlock/ListBlock already
        render nothing for an empty field) -- QUICK/WHY_THIS_SETUP/WHY_NOT/
        CATALYST/ANALOGS are materially distinct presentations of the exact
        same evidence, never the same template with a different label."""
        supporting = [c.statement for c in _claims_by_direction(claims, ClaimDirection.SUPPORTING)]
        contradicting = [c.statement for c in _claims_by_direction(claims, ClaimDirection.CONTRADICTING)]
        unknown = [c.statement for c in _claims_by_direction(claims, ClaimDirection.UNKNOWN)]
        refs = sorted({ref for c in claims for ref in c.evidence_refs})
        invalidation = self.generate_monitoring_summary(packet, claims)

        situation_summary = (
            f"{packet.symbol} ({packet.timeframe}) as of {_format_exchange_timestamp(packet.as_of)}. "
            f"RANKING GATE: {packet.ranking_gate_status}."
        )
        catalyst_text = (
            packet.catalyst_context.label_basis
            if packet.catalyst_context is not None
            else "No catalyst context available."
        )
        # Hardening pass (§Y): "formal statistical research" (Phase 8/9's
        # purged-episode statistical cohort) and "historical analog search"
        # (Phase 9's nearest-neighbor setup ledger search) are two distinct
        # systems with independent availability -- never described with
        # language that reads as one system when only one half exists.
        historical_text = (
            packet.historical_research.independence.evidence_maturity_basis
            if packet.historical_research is not None
            else "Formal statistical research is unavailable for this packet's as_of. This does not "
            "imply historical analog search is unavailable -- see the separate Historical Analogs section."
        )

        fields = _MODE_BUILDERS[mode](
            packet=packet,
            claims=claims,
            supporting=supporting,
            contradicting=contradicting,
            unknown=unknown,
            invalidation=invalidation,
            situation_summary=situation_summary,
            setup_explanation=self.explain_setup(packet, claims),
            catalyst_text=catalyst_text,
            historical_text=historical_text,
        )

        return ResearchBrief(
            brief_id=_brief_id(packet.packet_id, mode),
            evidence_packet_id=packet.packet_id,
            mode=mode,
            evidence_refs=refs,
            generated_at=datetime.now(timezone.utc),
            as_of=packet.as_of,
            provider=self.name,
            model=None,
            prompt_version=RESEARCH_BRIEF_PROMPT_VERSION,
            **fields,
        )
