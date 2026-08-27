from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.outcomes import evaluate_setup_outcome
from app.research.replay import run_replay
from app.research_intelligence.baselines import compute_direction_matched_baseline
from app.research_intelligence.evidence_card import build_evidence_card
from app.research_intelligence.partitions import build_partition_plan, partition_for_timestamp
from app.research_intelligence.schemas import EvidenceQualityFlag
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _entries_with_outcomes():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "evidence-card-test")
    entries = []
    for e in result.ledger_entries:
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)
    return entries, result.baseline_samples


def test_evidence_card_basic_fields_populated_from_real_data():
    entries, _ = _entries_with_outcomes()
    trend_qualified = [
        e for e in entries if e.setup_type == "trend_pullback" and e.detection.current_state == "qualified"
    ]
    card = build_evidence_card(
        "trend_pullback", trend_qualified, horizon_bars=5, timeframe=Timeframe.ONE_HOUR
    )
    assert card.setup_type == "trend_pullback"
    assert card.horizon_bars == 5
    assert card.sample_count == len(trend_qualified)


def test_evidence_card_small_sample_flag_on_the_real_thin_fixture():
    entries, _ = _entries_with_outcomes()
    trend_qualified = [
        e for e in entries if e.setup_type == "trend_pullback" and e.detection.current_state == "qualified"
    ]
    card = build_evidence_card(
        "trend_pullback", trend_qualified, horizon_bars=5, timeframe=Timeframe.ONE_HOUR
    )
    # The real 250-bar fixture never has 20+ trend_pullback qualified
    # entries -- this must show up honestly as a small/insufficient flag.
    assert (
        EvidenceQualityFlag.SMALL_SAMPLE in card.flags
        or EvidenceQualityFlag.INSUFFICIENT_SAMPLE in card.flags
    )


def test_evidence_card_with_baseline_computes_observed_excess():
    entries, baseline_samples = _entries_with_outcomes()
    qualified = [
        e for e in entries if e.setup_type == "trend_pullback" and e.detection.current_state == "qualified"
    ]
    from app.market_structure.schemas import Direction

    baseline_stats = compute_direction_matched_baseline(
        SPY_1H, baseline_samples, Direction.BULLISH, (1, 3, 5, 10, 20), min_bucket_size=1
    )
    card = build_evidence_card(
        "trend_pullback",
        qualified,
        horizon_bars=5,
        timeframe=Timeframe.ONE_HOUR,
        baseline_stats=baseline_stats,
    )
    assert card.matched_baseline_median is not None
    if card.median_directional_return is not None:
        expected = card.median_directional_return - card.matched_baseline_median
        assert abs(card.observed_excess - expected) < 1e-9


def test_evidence_card_partition_medians_present_with_mapping():
    entries, _ = _entries_with_outcomes()
    trend_entries = [e for e in entries if e.setup_type == "trend_pullback"]
    plan = build_partition_plan(SYMBOL, "1h", sorted(c.timestamp for c in SPY_1H))
    partition_by_setup_id = {
        e.setup_id: partition_for_timestamp(plan, e.candidate_candle_timestamp) for e in trend_entries
    }
    card = build_evidence_card(
        "trend_pullback",
        trend_entries,
        horizon_bars=5,
        timeframe=Timeframe.ONE_HOUR,
        partition_by_setup_id=partition_by_setup_id,
    )
    assert set(card.partition_medians.keys()) == {"development", "validation", "test"}


def test_evidence_card_multiple_comparison_flag_from_explicit_count():
    entries, _ = _entries_with_outcomes()
    qualified = [e for e in entries if e.detection.current_state == "qualified"]
    card = build_evidence_card(
        "any", qualified, horizon_bars=5, timeframe=Timeframe.ONE_HOUR, comparisons_displayed_count=50
    )
    assert EvidenceQualityFlag.MULTIPLE_COMPARISON_WARNING in card.flags


def test_evidence_card_data_limitation_flag_passthrough():
    entries, _ = _entries_with_outcomes()
    card = build_evidence_card(
        "any",
        entries,
        horizon_bars=5,
        timeframe=Timeframe.ONE_HOUR,
        data_limitation_notes=["provider capped at 730 days"],
    )
    assert EvidenceQualityFlag.DATA_LIMITATION in card.flags


def test_evidence_card_deterministic_bootstrap_for_the_same_seed():
    entries, _ = _entries_with_outcomes()
    qualified = [e for e in entries if e.detection.current_state == "qualified"]
    card_a = build_evidence_card("any", qualified, horizon_bars=5, timeframe=Timeframe.ONE_HOUR, seed=42)
    card_b = build_evidence_card("any", qualified, horizon_bars=5, timeframe=Timeframe.ONE_HOUR, seed=42)
    assert card_a.bootstrap_interval.lower == card_b.bootstrap_interval.lower
    assert card_a.bootstrap_interval.upper == card_b.bootstrap_interval.upper


def test_evidence_card_handles_empty_entries_without_crashing():
    card = build_evidence_card("trend_pullback", [], horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert card.sample_count == 0
    assert card.median_directional_return is None
    assert EvidenceQualityFlag.INSUFFICIENT_SAMPLE in card.flags


def test_evidence_card_phase_9_independence_fields_are_populated_on_real_data():
    entries, _ = _entries_with_outcomes()
    qualified = [e for e in entries if e.detection.current_state == "qualified"]
    card = build_evidence_card("any", qualified, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)

    assert card.independent_episode_count is not None
    assert card.independent_episode_count <= card.sample_count
    assert card.purged_sample_count is not None
    assert card.purged_sample_count <= card.sample_count
    assert card.overlap_rate is not None
    assert 0.0 <= card.overlap_rate <= 1.0
    assert card.bootstrap_method is not None
    assert card.walk_forward_stability in {"stable", "unstable", "insufficient_data"}
    assert card.symbol_coverage_count == card.symbols_total
    assert card.temporal_coverage_buckets >= 0


def test_evidence_card_purged_sample_count_uses_the_override_horizon():
    entries, _ = _entries_with_outcomes()
    qualified = [e for e in entries if e.detection.current_state == "qualified"]
    card_default = build_evidence_card("any", qualified, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    card_override = build_evidence_card(
        "any", qualified, horizon_bars=5, timeframe=Timeframe.ONE_HOUR, purged_horizon_bars=20
    )
    # A wider horizon excludes at least as much -- purged count can only
    # shrink or stay the same, never grow, as the exclusion window widens.
    assert card_override.purged_sample_count <= card_default.purged_sample_count


def test_evidence_card_conclusion_stability_report_can_trigger_purged_result_reversal_flag():
    from app.research_intelligence.schemas import (
        BootstrapInterval,
        ConclusionLabel,
        ConclusionStabilityReport,
    )
    from app.research_intelligence.schemas import DistributionSummary as _DS
    from app.research_intelligence.schemas import GroupComparisonResult as _GCR

    def _comparison():
        return _GCR(
            group_a_label="a",
            group_b_label="b",
            horizon_bars=5,
            group_a_distribution=_DS(n=50, median=1.0),
            group_b_distribution=_DS(n=50, median=1.0),
            median_difference=1.0,
            median_difference_bootstrap=BootstrapInterval(available=False, statistic="median"),
        )

    reversal_report = ConclusionStabilityReport(
        finding_label="test",
        horizon_bars=5,
        raw=_comparison(),
        episode=_comparison(),
        purged=_comparison(),
        label=ConclusionLabel.REVERSES,
        label_basis="test",
    )
    entries, _ = _entries_with_outcomes()
    qualified = [e for e in entries if e.detection.current_state == "qualified"]
    card = build_evidence_card(
        "any",
        qualified,
        horizon_bars=5,
        timeframe=Timeframe.ONE_HOUR,
        conclusion_stability_report=reversal_report,
    )
    assert EvidenceQualityFlag.PURGED_RESULT_REVERSAL in card.flags
