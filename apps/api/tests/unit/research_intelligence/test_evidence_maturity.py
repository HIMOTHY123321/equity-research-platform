from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
from app.research_intelligence.evidence_maturity import classify_evidence_maturity
from app.research_intelligence.schemas import (
    BootstrapInterval,
    ConclusionLabel,
    ConclusionStabilityReport,
    DistributionSummary,
    EvidenceMaturity,
    EvidenceQualityFlag,
    GroupComparisonResult,
    ResearchEvidenceCard,
)

_CONFIG = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
_UNAVAILABLE_BOOTSTRAP = BootstrapInterval(available=False, statistic="median")


def _card(
    purged_sample_count=100,
    walk_forward_stability="stable",
    symbols_positive=3,
    symbol_coverage_count=3,
    flags=None,
) -> ResearchEvidenceCard:
    return ResearchEvidenceCard(
        setup_type="breakout_retest",
        horizon_bars=5,
        sample_count=200,
        sample_size_label="larger",
        bootstrap_interval=_UNAVAILABLE_BOOTSTRAP,
        symbols_positive=symbols_positive,
        symbols_total=symbol_coverage_count,
        purged_sample_count=purged_sample_count,
        walk_forward_stability=walk_forward_stability,
        symbol_coverage_count=symbol_coverage_count,
        flags=flags or [],
    )


def _comparison(label_input_n=50) -> GroupComparisonResult:
    return GroupComparisonResult(
        group_a_label="a",
        group_b_label="b",
        horizon_bars=5,
        group_a_distribution=DistributionSummary(n=label_input_n, median=1.0),
        group_b_distribution=DistributionSummary(n=label_input_n, median=1.0),
        median_difference=1.0,
        median_difference_bootstrap=_UNAVAILABLE_BOOTSTRAP,
    )


def _conclusion(label: ConclusionLabel) -> ConclusionStabilityReport:
    return ConclusionStabilityReport(
        finding_label="test",
        horizon_bars=5,
        raw=_comparison(),
        episode=_comparison(),
        purged=_comparison(),
        label=label,
        label_basis="test",
    )


def test_insufficient_when_purged_sample_below_small_sample_min():
    card = _card(purged_sample_count=_CONFIG.small_sample_min - 1)
    maturity, basis = classify_evidence_maturity(card)
    assert maturity == EvidenceMaturity.INSUFFICIENT
    assert "purged sample" in basis


def test_insufficient_when_purged_sample_count_is_none():
    card = _card(purged_sample_count=None)
    maturity, _ = classify_evidence_maturity(card)
    assert maturity == EvidenceMaturity.INSUFFICIENT


def test_mixed_when_conclusion_stability_disagrees_even_with_a_large_sample():
    # A huge, stable, cross-symbol-agreeing sample -- but the finding itself
    # does not survive independence adjustment. MIXED must win over REPLICATED.
    card = _card(purged_sample_count=1000, walk_forward_stability="stable")
    for label in (ConclusionLabel.WEAKENS, ConclusionLabel.DISAPPEARS, ConclusionLabel.REVERSES):
        maturity, basis = classify_evidence_maturity(card, conclusion_stability_report=_conclusion(label))
        assert maturity == EvidenceMaturity.MIXED
        assert label.value in basis


def test_replicated_requires_every_condition_at_once():
    card = _card(
        purged_sample_count=_CONFIG.moderate_sample_min,
        walk_forward_stability="stable",
        symbols_positive=3,
        symbol_coverage_count=3,
        flags=[],
    )
    maturity, basis = classify_evidence_maturity(
        card, conclusion_stability_report=_conclusion(ConclusionLabel.SURVIVES)
    )
    assert maturity == EvidenceMaturity.REPLICATED
    assert "moderate_sample_min" in basis


def test_replicated_works_without_a_conclusion_stability_report_supplied():
    card = _card(
        purged_sample_count=_CONFIG.moderate_sample_min,
        walk_forward_stability="stable",
        symbols_positive=2,
        symbol_coverage_count=2,
        flags=[],
    )
    maturity, _ = classify_evidence_maturity(card, conclusion_stability_report=None)
    assert maturity == EvidenceMaturity.REPLICATED


def test_preliminary_when_purged_sample_meets_bar_but_walk_forward_unstable():
    card = _card(
        purged_sample_count=_CONFIG.moderate_sample_min,
        walk_forward_stability="unstable",
        symbols_positive=3,
        symbol_coverage_count=3,
    )
    maturity, basis = classify_evidence_maturity(card)
    assert maturity == EvidenceMaturity.PRELIMINARY
    assert "walk-forward stability is unstable" in basis


def test_preliminary_when_only_some_symbols_agree_in_sign():
    card = _card(
        purged_sample_count=_CONFIG.moderate_sample_min,
        walk_forward_stability="stable",
        symbols_positive=2,
        symbol_coverage_count=3,
    )
    maturity, basis = classify_evidence_maturity(card)
    assert maturity == EvidenceMaturity.PRELIMINARY
    assert "2/3 symbols agree" in basis


def test_preliminary_when_only_a_single_symbol_has_data():
    card = _card(
        purged_sample_count=_CONFIG.moderate_sample_min,
        walk_forward_stability="stable",
        symbols_positive=1,
        symbol_coverage_count=1,
    )
    maturity, _ = classify_evidence_maturity(card)
    assert maturity == EvidenceMaturity.PRELIMINARY


def test_preliminary_when_a_fragile_independence_flag_is_present():
    card = _card(
        purged_sample_count=_CONFIG.moderate_sample_min,
        walk_forward_stability="stable",
        symbols_positive=3,
        symbol_coverage_count=3,
        flags=[EvidenceQualityFlag.HIGH_OVERLAP],
    )
    maturity, basis = classify_evidence_maturity(card)
    assert maturity == EvidenceMaturity.PRELIMINARY
    assert "high_overlap" in basis


def test_preliminary_when_purged_sample_is_small_sample_min_but_not_moderate():
    # Above small_sample_min (not INSUFFICIENT) but below moderate_sample_min
    # (not enough for REPLICATED either).
    card = _card(purged_sample_count=_CONFIG.small_sample_min, walk_forward_stability="stable")
    maturity, basis = classify_evidence_maturity(card)
    assert maturity == EvidenceMaturity.PRELIMINARY
    assert "moderate_sample_min" in basis
