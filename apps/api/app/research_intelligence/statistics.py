"""Distribution statistics (#9). Every research result that reports a
directional-return, MFE/MAE, or bars-to-extreme number goes through this
module -- never a bare average. Percentiles use linear interpolation
(numpy's default "linear" method), matching the common statistical
convention.
"""

from __future__ import annotations

import statistics as pystats

import numpy as np

from app.research.schemas import SampleSizeLabel
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import DistributionSummary


def summarize_distribution(values: list) -> DistributionSummary:
    """Never raises on an empty or single-value sample -- returns whatever
    subset of statistics is well-defined for that sample size (n=0: none;
    n=1: mean/median only, no spread; n>=2: everything)."""
    n = len(values)
    if n == 0:
        return DistributionSummary(n=0)

    arr = np.asarray(values, dtype=float)
    mean = float(np.mean(arr))
    median = float(np.median(arr))

    if n == 1:
        return DistributionSummary(n=1, mean=mean, median=median)

    stdev = float(pystats.stdev(values))
    p10, p25, p75, p90 = (float(x) for x in np.percentile(arr, [10, 25, 75, 90]))
    return DistributionSummary(n=n, mean=mean, median=median, stdev=stdev, p10=p10, p25=p25, p75=p75, p90=p90)


def sample_size_label(
    n: int, config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
) -> SampleSizeLabel:
    """Descriptive-only labeling (#22, matching app/research/config.py's
    existing thresholds) -- never a claim of statistical significance."""
    if n < config.small_sample_min:
        return SampleSizeLabel.INSUFFICIENT
    if n < config.moderate_sample_min:
        return SampleSizeLabel.SMALL
    if n < config.larger_sample_min:
        return SampleSizeLabel.MODERATE
    return SampleSizeLabel.LARGER
