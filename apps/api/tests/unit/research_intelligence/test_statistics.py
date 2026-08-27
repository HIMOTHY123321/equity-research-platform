import math

from app.research.schemas import SampleSizeLabel
from app.research_intelligence.statistics import sample_size_label, summarize_distribution


def test_hand_calculated_distribution_for_four_values():
    # values = [1, 2, 3, 4]; every figure below is hand-calculated, not
    # derived from re-running the code under test.
    summary = summarize_distribution([1, 2, 3, 4])
    assert summary.n == 4
    assert summary.mean == 2.5
    assert summary.median == 2.5
    assert math.isclose(summary.stdev, 1.2909944487358056, rel_tol=1e-9)
    # Linear-interpolation percentiles: position = (n-1)*p/100.
    assert math.isclose(summary.p10, 1.3, rel_tol=1e-9)
    assert math.isclose(summary.p25, 1.75, rel_tol=1e-9)
    assert math.isclose(summary.p75, 3.25, rel_tol=1e-9)
    assert math.isclose(summary.p90, 3.7, rel_tol=1e-9)


def test_hand_calculated_distribution_is_order_independent():
    shuffled = summarize_distribution([3, 1, 4, 2])
    assert shuffled.mean == 2.5
    assert shuffled.median == 2.5
    assert math.isclose(shuffled.stdev, 1.2909944487358056, rel_tol=1e-9)


def test_empty_sample_returns_n_zero_and_no_fabricated_statistics():
    summary = summarize_distribution([])
    assert summary.n == 0
    assert summary.mean is None
    assert summary.median is None
    assert summary.stdev is None
    assert summary.p10 is None


def test_single_value_sample_has_mean_and_median_but_no_spread():
    summary = summarize_distribution([42.0])
    assert summary.n == 1
    assert summary.mean == 42.0
    assert summary.median == 42.0
    assert summary.stdev is None
    assert summary.p25 is None


def test_sample_size_label_boundaries_are_hand_verified():
    assert sample_size_label(19) == SampleSizeLabel.INSUFFICIENT
    assert sample_size_label(20) == SampleSizeLabel.SMALL
    assert sample_size_label(49) == SampleSizeLabel.SMALL
    assert sample_size_label(50) == SampleSizeLabel.MODERATE
    assert sample_size_label(199) == SampleSizeLabel.MODERATE
    assert sample_size_label(200) == SampleSizeLabel.LARGER
