"""Phase 12 (#E): classify_evidence_quality's priority-ordered branches.

classify_evidence_quality is a pure function that only ever reads a fixed
set of attribute paths off `packet.historical_research` -- it is tested
here against lightweight SimpleNamespace fakes that duck-type exactly those
paths, rather than a fully-constructed CatalystResearchQueryResponse (whose
irrelevant required fields would add nothing but boilerplate to every case).
tests/unit/forecasting/test_deterministic.py and test_service.py separately
prove the classifier against a real, pipeline-built EvidencePacket.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.forecasting.config import DEFAULT_FORECAST_CONFIG
from app.forecasting.evidence_quality import classify_evidence_quality
from app.forecasting.schemas import EvidenceQualityState
from app.research_intelligence.schemas import ConclusionLabel, ContradictionStatus, EvidenceMaturity


def _research(
    maturity=EvidenceMaturity.REPLICATED.value,
    contradictions=(),
    stability_label=None,
    overlap_fraction=0.1,
    concentration_warnings=(),
):
    stability = SimpleNamespace(label=stability_label) if stability_label is not None else None
    return SimpleNamespace(
        independence=SimpleNamespace(evidence_maturity=maturity, conclusion_stability=stability),
        contradictions=[SimpleNamespace(status=s) for s in contradictions],
        overlap=SimpleNamespace(overlap_fraction=overlap_fraction),
        concentration=SimpleNamespace(warnings=list(concentration_warnings)),
    )


def _packet(research):
    return SimpleNamespace(historical_research=research)


def test_no_research_at_all_is_insufficient():
    assert classify_evidence_quality(_packet(None)) == EvidenceQualityState.INSUFFICIENT_EVIDENCE


def test_insufficient_maturity_is_insufficient():
    research = _research(maturity=EvidenceMaturity.INSUFFICIENT.value)
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.INSUFFICIENT_EVIDENCE


def test_reversing_conclusion_is_weak_even_with_replicated_maturity():
    research = _research(maturity=EvidenceMaturity.REPLICATED.value, stability_label=ConclusionLabel.REVERSES)
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.WEAK_EVIDENCE


def test_disappearing_conclusion_is_weak():
    research = _research(
        maturity=EvidenceMaturity.REPLICATED.value, stability_label=ConclusionLabel.DISAPPEARS
    )
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.WEAK_EVIDENCE


def test_replicated_clean_and_surviving_is_high_evidence_support():
    research = _research(maturity=EvidenceMaturity.REPLICATED.value, stability_label=ConclusionLabel.SURVIVES)
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.HIGH_EVIDENCE_SUPPORT


def test_replicated_with_no_stability_report_is_still_high_evidence_support():
    research = _research(maturity=EvidenceMaturity.REPLICATED.value, stability_label=None)
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.HIGH_EVIDENCE_SUPPORT


def test_unsupported_contradiction_downgrades_replicated_to_mixed():
    research = _research(
        maturity=EvidenceMaturity.REPLICATED.value,
        contradictions=[ContradictionStatus.NOT_SUPPORTED],
        stability_label=ConclusionLabel.SURVIVES,
    )
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.MIXED_EVIDENCE


def test_high_overlap_downgrades_replicated_to_mixed():
    research = _research(
        maturity=EvidenceMaturity.REPLICATED.value,
        overlap_fraction=0.9,
        stability_label=ConclusionLabel.SURVIVES,
    )
    result = classify_evidence_quality(_packet(research), DEFAULT_FORECAST_CONFIG)
    assert result == EvidenceQualityState.MIXED_EVIDENCE


def test_concentration_warning_downgrades_replicated_to_mixed():
    research = _research(
        maturity=EvidenceMaturity.REPLICATED.value,
        concentration_warnings=["single-symbol concentration"],
        stability_label=ConclusionLabel.SURVIVES,
    )
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.MIXED_EVIDENCE


def test_mixed_maturity_is_mixed_evidence():
    research = _research(maturity=EvidenceMaturity.MIXED.value)
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.MIXED_EVIDENCE


def test_preliminary_maturity_is_mixed_evidence():
    research = _research(maturity=EvidenceMaturity.PRELIMINARY.value)
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.MIXED_EVIDENCE


def test_unrecognized_maturity_falls_back_to_weak_not_high():
    research = _research(maturity="some_future_maturity_value_not_yet_defined")
    assert classify_evidence_quality(_packet(research)) == EvidenceQualityState.WEAK_EVIDENCE
