"""Phase 15 §10/§11/§12: assembles `CohortStatistics` for one cohort of
`ProspectiveObservation`s at one return horizon -- the single place that
ties together independence counts, distribution summary, bootstrap CI,
baseline comparison, cost sensitivity, and concentration warnings.
Reuses `app.research_intelligence` primitives wherever they are already
generic (bootstrap, statistics, effect size); episode/purge counts use
`app.validation.independence` (see that module's docstring for why).
"""

from __future__ import annotations

from typing import Optional

from app.research_intelligence.bootstrap import bootstrap_confidence_interval
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
from app.research_intelligence.statistics import summarize_distribution
from app.schemas.market_data import Timeframe
from app.validation.baselines import matched_baseline_median, observed_excess
from app.validation.concentration import detect_concentration
from app.validation.cost_sensitivity import apply_cost_sensitivity
from app.validation.independence import sample_counts
from app.validation.schemas import BaselineType, CohortStatistics, ProspectiveObservation

_HORIZON_FIELD = {1: "return_1", 3: "return_3", 5: "return_5", 10: "return_10", 20: "return_20"}


def _returns_for_horizon(observations: list[ProspectiveObservation], horizon_bars: int) -> list[float]:
    field = _HORIZON_FIELD[horizon_bars]
    return [v for o in observations if (v := getattr(o, field)) is not None]


def build_cohort_statistics(
    cohort_label: str,
    observations: list[ProspectiveObservation],
    horizon_bars: int,
    timeframe: Timeframe,
    *,
    seed: int = 0,
    baseline_type: Optional[BaselineType] = None,
    baseline_comparison_returns: Optional[list[float]] = None,
) -> CohortStatistics:
    # Phase 15 per-horizon resolution: an observation whose OTHER horizons
    # are still pending (resolution_quality=PARTIAL, resolved=False) can
    # already have a valid return for THIS horizon -- so the return series
    # is drawn from every observation carrying a non-None value for this
    # specific horizon field, not gated on full (all-5-horizons) resolution.
    # `resolved` (fully-resolved-across-all-horizons) is still the correct
    # gate for whole-window stats like MFE/MAE/invalidation/exit rate,
    # which only ever populate once the legacy full-window pass completes.
    returns = _returns_for_horizon(observations, horizon_bars)
    horizon_field = _HORIZON_FIELD[horizon_bars]
    has_horizon = [o for o in observations if getattr(o, horizon_field) is not None]
    raw_n, independent_n, purged_n = sample_counts(has_horizon, horizon_bars, timeframe)
    resolved = [o for o in observations if o.resolved]

    distribution = summarize_distribution(returns)
    positive_rate = (sum(1 for r in returns if r > 0) / len(returns)) if returns else None

    mfe_values = [o.mfe_atr for o in resolved if o.mfe_atr is not None]
    mae_values = [o.mae_atr for o in resolved if o.mae_atr is not None]
    invalidated = sum(1 for o in resolved if o.decision_state == "invalidated")
    exited = sum(1 for o in resolved if o.decision_state == "exit_conditions_met")

    bootstrap = bootstrap_confidence_interval(
        returns, "median", seed=seed, config=DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
    )

    baseline_median = (
        matched_baseline_median(baseline_type, baseline_comparison_returns or [])
        if baseline_type is not None
        else None
    )

    return CohortStatistics(
        cohort_label=cohort_label,
        horizon_bars=horizon_bars,
        raw_n=raw_n,
        independent_n=independent_n,
        purged_n=purged_n,
        mean=distribution.mean,
        median=distribution.median,
        stdev=distribution.stdev,
        p25=distribution.p25,
        p75=distribution.p75,
        positive_rate=positive_rate,
        mfe_atr_median=(sorted(mfe_values)[len(mfe_values) // 2] if mfe_values else None),
        mae_atr_median=(sorted(mae_values)[len(mae_values) // 2] if mae_values else None),
        invalidation_rate=(invalidated / len(resolved)) if resolved else None,
        exit_rate=(exited / len(resolved)) if resolved else None,
        bootstrap_available=bootstrap.available,
        bootstrap_point_estimate=bootstrap.point_estimate,
        bootstrap_lower=bootstrap.lower,
        bootstrap_upper=bootstrap.upper,
        bootstrap_method="iid_percentile",
        baseline_type=baseline_type,
        baseline_median=baseline_median,
        effect_vs_baseline=observed_excess(distribution.median, baseline_median),
        cost_sensitivity=apply_cost_sensitivity(returns),
        concentration_warnings=detect_concentration(resolved),
    )
