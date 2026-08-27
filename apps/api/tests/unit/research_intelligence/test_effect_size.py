import math

from app.research_intelligence.effect_size import (
    cliffs_delta,
    difference_of_means,
    difference_of_medians,
    standardized_effect_size,
)


def test_difference_of_medians_and_means_hand_calculated():
    a = [1, 2, 3, 4, 5]
    b = [2, 3, 4, 5, 6]
    assert difference_of_medians(a, b) == -1.0
    assert difference_of_means(a, b) == -1.0


def test_differences_are_none_for_an_empty_group():
    assert difference_of_medians([], [1, 2]) is None
    assert difference_of_means([1, 2], []) is None


def test_standardized_effect_size_hand_calculated():
    a = [1, 2, 3, 4, 5]
    b = [2, 3, 4, 5, 6]
    d = standardized_effect_size(a, b)
    assert math.isclose(d, -0.6324555320336759, rel_tol=1e-9)


def test_standardized_effect_size_is_none_for_zero_pooled_variance():
    # Every value identical in both groups -- pooled stdev is exactly zero.
    assert standardized_effect_size([5.0, 5.0], [5.0, 5.0]) is None


def test_standardized_effect_size_is_none_below_two_observations():
    assert standardized_effect_size([1.0], [1.0, 2.0]) is None


def test_cliffs_delta_is_plus_one_when_every_a_exceeds_every_b():
    assert cliffs_delta([1, 2, 3], [0, 0, 0]) == 1.0


def test_cliffs_delta_is_minus_one_when_every_a_is_below_every_b():
    assert cliffs_delta([1, 2, 3], [4, 5, 6]) == -1.0


def test_cliffs_delta_hand_calculated_with_ties():
    # a=[1,2,3], b=[2,2,2]: a=1 loses to all 3, a=2 ties all 3 (uncounted),
    # a=3 beats all 3 -- 3 greater, 3 less, delta = 0/9 = 0.
    assert cliffs_delta([1, 2, 3], [2, 2, 2]) == 0.0


def test_cliffs_delta_is_none_for_an_empty_group():
    assert cliffs_delta([], [1, 2]) is None
