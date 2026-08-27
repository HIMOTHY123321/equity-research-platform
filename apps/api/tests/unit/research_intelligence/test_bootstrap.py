import pytest

from app.research_intelligence.bootstrap import bootstrap_confidence_interval
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG


def test_same_input_and_seed_produce_the_same_interval():
    values = [1.0, 2.0, 3.0, 4.0, 5.0] * 6  # n=30, above the min sample size
    result_a = bootstrap_confidence_interval(values, "mean", seed=42)
    result_b = bootstrap_confidence_interval(values, "mean", seed=42)
    assert result_a.lower == result_b.lower
    assert result_a.upper == result_b.upper
    assert result_a.point_estimate == result_b.point_estimate == 3.0


def test_different_seeds_can_produce_different_intervals():
    values = list(range(30))
    result_a = bootstrap_confidence_interval(values, "mean", seed=1)
    result_b = bootstrap_confidence_interval(values, "mean", seed=2)
    # Not asserting inequality (they could coincidentally match), just that
    # both are valid, available, distinct resampling runs.
    assert result_a.available and result_b.available
    assert result_a.seed == 1
    assert result_b.seed == 2


def test_insufficient_sample_is_unavailable_not_a_fabricated_narrow_interval():
    result = bootstrap_confidence_interval([1.0, 2.0, 3.0], "mean", seed=7)
    assert result.available is False
    assert result.lower is None
    assert result.upper is None
    assert "below the minimum" in result.unavailable_reason


def test_interval_brackets_the_point_estimate_for_a_known_fixture():
    # A symmetric, well-behaved sample -- the interval must contain the
    # point estimate, and lower must never exceed upper.
    values = [10.0, 12.0, 11.0, 13.0, 9.0, 10.5, 11.5, 12.5, 9.5, 10.0] * 3
    result = bootstrap_confidence_interval(values, "mean", seed=99)
    assert result.available
    assert result.lower <= result.point_estimate <= result.upper


def test_median_statistic_is_supported_and_labeled_correctly():
    values = list(range(1, 31))
    result = bootstrap_confidence_interval(values, "median", seed=5)
    assert result.statistic == "median"
    assert result.point_estimate == 15.5


def test_unsupported_statistic_is_rejected():
    with pytest.raises(ValueError, match="unsupported bootstrap statistic"):
        bootstrap_confidence_interval(list(range(30)), "mode", seed=1)


def test_confidence_level_and_iterations_are_recorded_on_the_result():
    result = bootstrap_confidence_interval(list(range(30)), "mean", seed=1)
    assert result.confidence_level == DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.bootstrap_confidence_level
    assert result.iterations == DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.bootstrap_iterations
