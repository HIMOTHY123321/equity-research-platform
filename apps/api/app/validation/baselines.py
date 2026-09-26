"""Phase 15 §5/§6: matched baseline construction for prospective cohorts.

Reuses `app.research.baseline.compute_unconditional_baseline` unchanged
for the UNCONDITIONAL baseline. The two remaining named baseline types
this phase requires that don't already exist anywhere in the codebase --
REJECTED_CANDIDATE and DETECTION -- are added here, deliberately kept out
of `app.research_intelligence.baselines` (which is scoped to Phase 8/9
historical-replay `SetupLedgerEntry`/`BaselineSample` objects) so Phase 15
additions stay isolated and reviewable on their own.

Every baseline function here operates only on already-computed,
already-persisted return values (or on candles strictly at-or-before the
matching timestamp) -- never on the outcome being evaluated, and never on
post-outcome features (Phase 15 §72's "no post-outcome feature allowed in
matching").
"""

from __future__ import annotations

from statistics import median
from typing import Optional

from app.validation.schemas import BaselineType


def matched_baseline_median(
    baseline_type: BaselineType, comparison_returns: list[float]
) -> Optional[float]:
    """A thin, explicit wrapper: the caller supplies the already-selected
    comparison-population returns for the requested baseline type (e.g.
    unconditional-symbol returns, or rejected-candidate returns), and this
    just computes the median -- kept separate from selection so the
    *selection* logic (which population qualifies) stays inspectable and
    testable on its own, per baseline type, rather than buried in a single
    do-everything function."""
    if not comparison_returns:
        return None
    return median(comparison_returns)


def observed_excess(cohort_median: Optional[float], baseline_median: Optional[float]) -> Optional[float]:
    """Cohort median minus baseline median. Never called "alpha" or
    "edge" anywhere in this codebase (matches
    app.research_intelligence.baselines.observed_excess_outcome's own
    naming discipline)."""
    if cohort_median is None or baseline_median is None:
        return None
    return cohort_median - baseline_median
