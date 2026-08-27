"""Bootstrap confidence intervals (#10). Deterministic seeds throughout --
the same input + seed always produces the same interval, which is what
makes this testable without flakiness and reproducible across research
runs. Never labeled "probability of success"; the interval is a
description of estimation uncertainty in a sample statistic, not a claim
about any single future trade.
"""

from __future__ import annotations

import numpy as np

from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import BootstrapInterval

_STATISTIC_FNS = {"mean": np.mean, "median": np.median}


def bootstrap_confidence_interval(
    values: list,
    statistic: str,
    seed: int,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> BootstrapInterval:
    if statistic not in _STATISTIC_FNS:
        raise ValueError(
            f"unsupported bootstrap statistic {statistic!r}; expected one of {sorted(_STATISTIC_FNS)}"
        )

    n = len(values)
    if n < config.bootstrap_min_sample:
        return BootstrapInterval(
            available=False,
            statistic=statistic,
            unavailable_reason=(
                f"sample size {n} is below the minimum of {config.bootstrap_min_sample} "
                "required for a bootstrap interval"
            ),
        )

    stat_fn = _STATISTIC_FNS[statistic]
    arr = np.asarray(values, dtype=float)
    point_estimate = float(stat_fn(arr))

    rng = np.random.default_rng(seed)
    resample_stats = np.empty(config.bootstrap_iterations, dtype=float)
    for i in range(config.bootstrap_iterations):
        resample = rng.choice(arr, size=n, replace=True)
        resample_stats[i] = stat_fn(resample)

    alpha = 1.0 - config.bootstrap_confidence_level
    lower, upper = np.percentile(resample_stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])

    return BootstrapInterval(
        available=True,
        statistic=statistic,
        point_estimate=point_estimate,
        lower=float(lower),
        upper=float(upper),
        confidence_level=config.bootstrap_confidence_level,
        iterations=config.bootstrap_iterations,
        seed=seed,
    )


def bootstrap_difference_confidence_interval(
    a: list,
    b: list,
    statistic: str,
    seed: int,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> BootstrapInterval:
    """A two-sample bootstrap interval for statistic(a) - statistic(b) (used
    by #15/#16's group comparisons). Each group is resampled independently
    with replacement on every iteration -- this does not assume the two
    groups are paired or the same size."""
    if statistic not in _STATISTIC_FNS:
        raise ValueError(
            f"unsupported bootstrap statistic {statistic!r}; expected one of {sorted(_STATISTIC_FNS)}"
        )

    label = f"difference_of_{statistic}"
    n_a, n_b = len(a), len(b)
    if n_a < config.bootstrap_min_sample or n_b < config.bootstrap_min_sample:
        return BootstrapInterval(
            available=False,
            statistic=label,
            unavailable_reason=(
                f"group sizes ({n_a}, {n_b}) must both be at least {config.bootstrap_min_sample} "
                "for a bootstrap interval"
            ),
        )

    stat_fn = _STATISTIC_FNS[statistic]
    arr_a, arr_b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    point_estimate = float(stat_fn(arr_a) - stat_fn(arr_b))

    rng = np.random.default_rng(seed)
    diffs = np.empty(config.bootstrap_iterations, dtype=float)
    for i in range(config.bootstrap_iterations):
        resample_a = rng.choice(arr_a, size=n_a, replace=True)
        resample_b = rng.choice(arr_b, size=n_b, replace=True)
        diffs[i] = stat_fn(resample_a) - stat_fn(resample_b)

    alpha = 1.0 - config.bootstrap_confidence_level
    lower, upper = np.percentile(diffs, [100 * alpha / 2, 100 * (1 - alpha / 2)])

    return BootstrapInterval(
        available=True,
        statistic=label,
        point_estimate=point_estimate,
        lower=float(lower),
        upper=float(upper),
        confidence_level=config.bootstrap_confidence_level,
        iterations=config.bootstrap_iterations,
        seed=seed,
    )
