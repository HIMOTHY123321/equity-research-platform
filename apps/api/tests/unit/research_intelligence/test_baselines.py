from app.market_structure.schemas import Direction, TrendClass
from app.research.baseline import compute_regime_matched_baseline
from app.research.replay import run_replay
from app.research_intelligence.baselines import (
    compute_direction_matched_baseline,
    compute_structure_matched_baseline,
    horizon_stat_at,
    observed_excess_outcome,
)
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")
HORIZONS = (1, 3, 5, 10, 20)


def _real_replay():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    return run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "baseline-test-run")


def test_direction_matched_baseline_matches_regime_matched_baseline_by_construction():
    # Direction-matched IS regime-matched keyed on the setup's own
    # direction -- TrendClass and Direction share string values, so this
    # must produce byte-identical stats to calling the Phase 7 primitive
    # directly with regime="bullish".
    result = _real_replay()
    direction_stats = compute_direction_matched_baseline(
        SPY_1H, result.baseline_samples, Direction.BULLISH, HORIZONS, min_bucket_size=20
    )
    regime_stats = compute_regime_matched_baseline(
        SPY_1H, result.baseline_samples, "bullish", HORIZONS, min_bucket_size=20
    )
    assert direction_stats == regime_stats


def test_structure_matched_baseline_is_a_subset_of_direction_matched():
    result = _real_replay()
    direction_stats = compute_direction_matched_baseline(
        SPY_1H, result.baseline_samples, Direction.BULLISH, HORIZONS, min_bucket_size=1
    )
    structure_stats = compute_structure_matched_baseline(
        SPY_1H,
        result.baseline_samples,
        primary_trend=TrendClass.BULLISH,
        daily_structure=TrendClass.BULLISH,
        four_hour_structure=None,
        horizons=HORIZONS,
        min_bucket_size=1,
    )
    assert structure_stats is not None
    assert direction_stats is not None
    # More conditions can only narrow the sample, never widen it.
    assert structure_stats.sample_count <= direction_stats.sample_count


def test_structure_matched_baseline_with_no_conditions_matches_every_sample():
    result = _real_replay()
    unconditioned = compute_structure_matched_baseline(
        SPY_1H,
        result.baseline_samples,
        primary_trend=None,
        daily_structure=None,
        four_hour_structure=None,
        horizons=HORIZONS,
        min_bucket_size=1,
    )
    assert unconditioned is not None
    # sample_count is n at the shortest horizon (1 bar) -- the very last bar
    # in the series can never have a computable 1-bar forward return, so
    # this is exactly one less than the total number of matched bars.
    assert unconditioned.sample_count == len(result.baseline_samples) - 1


def test_below_min_bucket_size_returns_none_not_a_misleading_tiny_sample():
    result = _real_replay()
    stats = compute_direction_matched_baseline(
        SPY_1H, result.baseline_samples, Direction.BULLISH, HORIZONS, min_bucket_size=10_000
    )
    assert stats is None


def test_horizon_stat_at_finds_the_right_horizon_and_none_for_missing_stats():
    result = _real_replay()
    stats = compute_direction_matched_baseline(
        SPY_1H, result.baseline_samples, Direction.BULLISH, HORIZONS, min_bucket_size=1
    )
    stat = horizon_stat_at(stats, 5)
    assert stat is not None
    assert stat.horizon_bars == 5
    assert horizon_stat_at(stats, 999) is None
    assert horizon_stat_at(None, 5) is None


def test_observed_excess_outcome_is_hand_calculated_subtraction():
    from app.research.schemas import GroupOutcomeStats, HorizonStat, SampleSizeLabel

    setup_stats = GroupOutcomeStats(
        sample_count=30,
        sample_size_label=SampleSizeLabel.SMALL,
        directional_return_by_horizon=[HorizonStat(horizon_bars=5, n=30, median=0.42)],
    )
    baseline_stats = GroupOutcomeStats(
        sample_count=500,
        sample_size_label=SampleSizeLabel.LARGER,
        directional_return_by_horizon=[HorizonStat(horizon_bars=5, n=500, median=0.10)],
    )
    excess = observed_excess_outcome(setup_stats, baseline_stats, horizon_bars=5)
    assert excess is not None
    assert abs(excess - 0.32) < 1e-9


def test_observed_excess_outcome_is_none_when_baseline_is_unavailable():
    from app.research.schemas import GroupOutcomeStats, HorizonStat, SampleSizeLabel

    setup_stats = GroupOutcomeStats(
        sample_count=30,
        sample_size_label=SampleSizeLabel.SMALL,
        directional_return_by_horizon=[HorizonStat(horizon_bars=5, n=30, median=0.42)],
    )
    assert observed_excess_outcome(setup_stats, None, horizon_bars=5) is None
