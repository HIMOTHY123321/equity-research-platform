"""Phase 12 (#E): categorical evidence-quality classification, derived
purely from already-computed Phase 8/9 research-quality fields on the
EvidencePacket -- never a new statistic, never a model confidence score.
Priority-ordered (first matching rule wins), same "explicit priority order,
never a judgment call" convention app.research_intelligence.evidence_
maturity/decay already use.
"""

from __future__ import annotations

from app.ai_analysis.schemas import EvidencePacket
from app.forecasting.config import DEFAULT_FORECAST_CONFIG, ForecastConfig
from app.forecasting.schemas import EvidenceQualityState
from app.research_intelligence.schemas import ConclusionLabel, ContradictionStatus, EvidenceMaturity


def classify_evidence_quality(
    packet: EvidencePacket, config: ForecastConfig = DEFAULT_FORECAST_CONFIG
) -> EvidenceQualityState:
    research = packet.historical_research
    if research is None:
        return EvidenceQualityState.INSUFFICIENT_EVIDENCE

    maturity = research.independence.evidence_maturity
    if maturity == EvidenceMaturity.INSUFFICIENT.value:
        return EvidenceQualityState.INSUFFICIENT_EVIDENCE

    has_unsupported_contradiction = any(
        c.status == ContradictionStatus.NOT_SUPPORTED for c in research.contradictions
    )
    stability = research.independence.conclusion_stability
    if stability is not None and stability.label in (ConclusionLabel.REVERSES, ConclusionLabel.DISAPPEARS):
        return EvidenceQualityState.WEAK_EVIDENCE

    high_overlap = research.overlap.overlap_fraction >= config.high_overlap_fraction
    has_concentration_warning = bool(research.concentration.warnings)

    if (
        maturity == EvidenceMaturity.REPLICATED.value
        and not has_unsupported_contradiction
        and not high_overlap
        and not has_concentration_warning
        and (stability is None or stability.label == ConclusionLabel.SURVIVES)
    ):
        return EvidenceQualityState.HIGH_EVIDENCE_SUPPORT

    if has_unsupported_contradiction or high_overlap or has_concentration_warning:
        return EvidenceQualityState.MIXED_EVIDENCE

    if maturity in (EvidenceMaturity.MIXED.value, EvidenceMaturity.PRELIMINARY.value):
        return EvidenceQualityState.MIXED_EVIDENCE

    return EvidenceQualityState.WEAK_EVIDENCE
