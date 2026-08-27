from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.outcomes import evaluate_setup_outcome
from app.research.replay import run_replay
from app.research_intelligence.conclusion_stability import _classify_stability, conclusion_stability
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
from app.research_intelligence.schemas import (
    BootstrapInterval,
    ConclusionLabel,
    DistributionSummary,
    GroupComparisonResult,
)
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")

_CONFIG = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
_UNAVAILABLE_BOOTSTRAP = BootstrapInterval(available=False, statistic="median")


def _comparison(n: int, median_difference: float) -> GroupComparisonResult:
    return GroupComparisonResult(
        group_a_label="a",
        group_b_label="b",
        horizon_bars=5,
        group_a_distribution=DistributionSummary(n=n, median=1.0, mean=1.0),
        group_b_distribution=DistributionSummary(n=n, median=1.0, mean=1.0),
        median_difference=median_difference,
        median_difference_bootstrap=_UNAVAILABLE_BOOTSTRAP,
    )


def test_ratio_at_or_above_survives_threshold_survives():
    raw = _comparison(50, 1.0)
    purged = _comparison(50, 0.75)  # ratio = 0.75 >= 0.7
    label, basis = _classify_stability(raw, purged, _CONFIG)
    assert label == ConclusionLabel.SURVIVES
    assert "0.75" in basis


def test_ratio_between_disappears_and_survives_weakens():
    raw = _comparison(50, 1.0)
    purged = _comparison(50, 0.3)  # ratio = 0.3, between 0.1 and 0.7
    label, _ = _classify_stability(raw, purged, _CONFIG)
    assert label == ConclusionLabel.WEAKENS


def test_ratio_inside_disappears_band_disappears():
    raw = _comparison(50, 1.0)
    purged = _comparison(50, 0.05)  # ratio = 0.05, inside [-0.1, 0.1]
    label, _ = _classify_stability(raw, purged, _CONFIG)
    assert label == ConclusionLabel.DISAPPEARS


def test_ratio_at_disappears_upper_boundary_is_inclusive():
    raw = _comparison(50, 1.0)
    purged = _comparison(50, 0.1)  # ratio exactly 0.1 -> boundary is <=, so DISAPPEARS not WEAKENS
    label, _ = _classify_stability(raw, purged, _CONFIG)
    assert label == ConclusionLabel.DISAPPEARS


def test_negative_ratio_beyond_threshold_reverses():
    raw = _comparison(50, 1.0)
    purged = _comparison(50, -0.5)  # ratio = -0.5 < -0.1
    label, _ = _classify_stability(raw, purged, _CONFIG)
    assert label == ConclusionLabel.REVERSES


def test_small_purged_sample_is_insufficient_regardless_of_ratio():
    raw = _comparison(50, 1.0)
    purged = _comparison(5, 1.0)  # ratio would be 1.0 (perfect survival) but n is too small
    label, basis = _classify_stability(raw, purged, _CONFIG)
    assert label == ConclusionLabel.INSUFFICIENT_INDEPENDENT_SAMPLE
    assert "too small" in basis


def test_zero_raw_difference_is_insufficient_not_a_division_error():
    raw = _comparison(50, 0.0)
    purged = _comparison(50, 0.2)
    label, basis = _classify_stability(raw, purged, _CONFIG)
    assert label == ConclusionLabel.INSUFFICIENT_INDEPENDENT_SAMPLE
    assert "0.0" in basis


def test_missing_median_difference_is_insufficient():
    raw = _comparison(50, None)
    purged = _comparison(50, 0.2)
    label, _ = _classify_stability(raw, purged, _CONFIG)
    assert label == ConclusionLabel.INSUFFICIENT_INDEPENDENT_SAMPLE


def _real_entries_with_outcomes():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "stability-test")
    entries = []
    for e in result.ledger_entries:
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)
    return entries


def _qualified_and_rejected(entries):
    trend_entries = [e for e in entries if e.setup_type == "trend_pullback"]
    qualified = [e for e in trend_entries if e.detection.current_state == "qualified"]
    rejected = [e for e in trend_entries if e.detection.current_state == "rejected"]
    return qualified, rejected


def test_conclusion_stability_wires_raw_episode_purged_together_on_real_data():
    """Not a claim about which label real SPY data produces (that would be
    exactly the kind of pre-chosen answer Phase 9 forbids) -- just that the
    three levels are computed consistently: purged and episode sample sizes
    never exceed raw, every level's group counts match what went in, and a
    valid label always comes out."""
    entries = _real_entries_with_outcomes()
    qualified, rejected = _qualified_and_rejected(entries)

    report = conclusion_stability(
        qualified,
        rejected,
        group_a_label="qualified",
        group_b_label="rejected",
        finding_label="qualified vs rejected trend_pullback (test)",
        horizon_bars=5,
        timeframe=Timeframe.ONE_HOUR,
        seed=11,
    )

    assert report.raw.group_a_distribution.n == len(qualified)
    assert report.raw.group_b_distribution.n == len(rejected)
    assert report.purged.group_a_distribution.n <= report.raw.group_a_distribution.n
    assert report.purged.group_b_distribution.n <= report.raw.group_b_distribution.n
    assert report.episode.group_a_distribution.n <= report.raw.group_a_distribution.n
    assert report.episode.group_b_distribution.n <= report.raw.group_b_distribution.n
    assert report.label in list(ConclusionLabel)
    assert report.label_basis


def test_anti_leakage_conclusion_stability_ignores_future_outcomes():
    """Mandatory anti-leakage check: mutating every entry's outcome to a
    wildly different, fabricated value must not change which entries are
    selected at the episode or purged level -- membership and selection are
    computed purely from detection-time fields, never from `.outcome`."""
    entries = _real_entries_with_outcomes()
    qualified, rejected = _qualified_and_rejected(entries)

    kwargs = dict(
        group_a_label="qualified",
        group_b_label="rejected",
        finding_label="qualified vs rejected trend_pullback (test)",
        horizon_bars=5,
        timeframe=Timeframe.ONE_HOUR,
        seed=11,
    )
    before = conclusion_stability(qualified, rejected, **kwargs)

    def _fabricate(entry):
        if entry.outcome is None:
            return entry
        fake_horizons = [
            h.model_copy(update={"directional_return_percent": 999.0}) for h in entry.outcome.horizons
        ]
        return entry.model_copy(
            update={"outcome": entry.outcome.model_copy(update={"horizons": fake_horizons})}
        )

    mutated_qualified = [_fabricate(e) for e in qualified]
    mutated_rejected = [_fabricate(e) for e in rejected]
    after = conclusion_stability(mutated_qualified, mutated_rejected, **kwargs)

    assert before.raw.group_a_distribution.n == after.raw.group_a_distribution.n
    assert before.raw.group_b_distribution.n == after.raw.group_b_distribution.n
    assert before.purged.group_a_distribution.n == after.purged.group_a_distribution.n
    assert before.purged.group_b_distribution.n == after.purged.group_b_distribution.n
    assert before.episode.group_a_distribution.n == after.episode.group_a_distribution.n
    assert before.episode.group_b_distribution.n == after.episode.group_b_distribution.n
