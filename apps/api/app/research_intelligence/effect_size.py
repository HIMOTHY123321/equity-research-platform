"""Effect size measures beyond lift alone (#12). A positive median
difference alone says nothing about how reliably one group beats the
other -- these functions describe the *shape* of the difference, not just
its sign. None of these are a significance test; they are descriptive, and
callers must not present them as one (#12: "do not overstate
interpretation").
"""

from __future__ import annotations

from typing import Optional

import numpy as np


def difference_of_medians(a: list, b: list) -> Optional[float]:
    if not a or not b:
        return None
    return float(np.median(a) - np.median(b))


def difference_of_means(a: list, b: list) -> Optional[float]:
    if not a or not b:
        return None
    return float(np.mean(a) - np.mean(b))


def standardized_effect_size(a: list, b: list) -> Optional[float]:
    """Cohen's d using the pooled sample standard deviation. None when
    either group has fewer than 2 observations (stdev undefined) or the
    pooled stdev is exactly zero (every value identical -- division would
    be meaningless, not "infinite effect size")."""
    if len(a) < 2 or len(b) < 2:
        return None
    arr_a, arr_b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    var_a, var_b = arr_a.var(ddof=1), arr_b.var(ddof=1)
    n_a, n_b = len(a), len(b)
    pooled_var = ((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2)
    pooled_stdev = pooled_var**0.5
    if pooled_stdev == 0:
        return None
    return float((arr_a.mean() - arr_b.mean()) / pooled_stdev)


def cliffs_delta(a: list, b: list) -> Optional[float]:
    """(#12, preferred for skewed distributions.) delta = (n_greater -
    n_less) / (len(a) * len(b)), ranging from -1 (every a < every b) to +1
    (every a > every b), 0 meaning no consistent ordering. Uses a sorted
    binary-search count (O((n+m) log m)) rather than the naive O(n*m)
    pairwise comparison matrix -- baseline cohorts can run into the
    thousands of bars, and an n*m matrix at that scale is a real memory
    risk, not a hypothetical one."""
    if not a or not b:
        return None
    arr_a = np.asarray(a, dtype=float)
    sorted_b = np.sort(np.asarray(b, dtype=float))
    m = len(sorted_b)

    n_less_per_a = np.searchsorted(sorted_b, arr_a, side="left")  # b values strictly < a[i]
    n_leq_per_a = np.searchsorted(sorted_b, arr_a, side="right")  # b values <= a[i]

    n_greater = int(np.sum(n_less_per_a))  # pairs where a[i] > b
    n_less = int(np.sum(m - n_leq_per_a))  # pairs where a[i] < b
    return float((n_greater - n_less) / (len(a) * len(b)))
