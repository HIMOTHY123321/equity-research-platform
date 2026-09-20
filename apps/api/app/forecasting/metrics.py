"""Phase 12 (#H): prospective performance metrics. Every number here is a
plain count or average over an explicit, reported sample -- never a
probability, never a single blended score. `compute_performance` is the one
grouping engine; every "by X" breakdown in the Forecast Lab UI is this same
function with a different `group_key`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from app.forecasting.schemas import ForecastOutcome, ForecastOutcomeCategory, ForecastStatus, ForwardForecast


@dataclass(frozen=True)
class PerformanceBreakdown:
    group: str
    forecast_count: int
    active_count: int
    resolved_count: int
    abstained_count: int
    correct_count: int
    incorrect_count: int
    neutral_count: int
    directional_accuracy: Optional[float]
    average_forward_return_percent: Optional[float]
    average_mfe_atr: Optional[float]
    average_mae_atr: Optional[float]
    coverage_rate: Optional[float]
    abstention_rate: Optional[float]


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def compute_performance(
    forecasts: list[ForwardForecast],
    outcomes: dict[str, ForecastOutcome],
    group_key: Callable[[ForwardForecast], str] = lambda f: "all",
) -> list[PerformanceBreakdown]:
    by_group: dict[str, list[ForwardForecast]] = {}
    for forecast in forecasts:
        by_group.setdefault(group_key(forecast), []).append(forecast)

    breakdowns = []
    for group, group_forecasts in sorted(by_group.items()):
        active = sum(1 for f in group_forecasts if f.status == ForecastStatus.ACTIVE)
        abstained = sum(1 for f in group_forecasts if f.status == ForecastStatus.ABSTAINED)
        resolved_outcomes = [
            outcomes[f.forecast_id] for f in group_forecasts if f.forecast_id in outcomes
        ]
        correct = sum(1 for o in resolved_outcomes if o.outcome == ForecastOutcomeCategory.CORRECT)
        incorrect = sum(1 for o in resolved_outcomes if o.outcome == ForecastOutcomeCategory.INCORRECT)
        neutral = sum(
            1 for o in resolved_outcomes if o.outcome == ForecastOutcomeCategory.NEUTRAL_UNRESOLVED
        )
        scored = correct + incorrect
        returns = [
            o.actual_forward_return_percent
            for o in resolved_outcomes
            if o.actual_forward_return_percent is not None
        ]
        mfes = [o.actual_mfe_atr for o in resolved_outcomes if o.actual_mfe_atr is not None]
        maes = [o.actual_mae_atr for o in resolved_outcomes if o.actual_mae_atr is not None]

        total = len(group_forecasts)
        coverage_denominator = total
        breakdowns.append(
            PerformanceBreakdown(
                group=group,
                forecast_count=total,
                active_count=active,
                resolved_count=len(resolved_outcomes),
                abstained_count=abstained,
                correct_count=correct,
                incorrect_count=incorrect,
                neutral_count=neutral,
                directional_accuracy=(correct / scored) if scored else None,
                average_forward_return_percent=_mean(returns),
                average_mfe_atr=_mean(mfes),
                average_mae_atr=_mean(maes),
                coverage_rate=(
                    (len(resolved_outcomes) / coverage_denominator) if coverage_denominator else None
                ),
                abstention_rate=(abstained / coverage_denominator) if coverage_denominator else None,
            )
        )
    return breakdowns


def overall_performance(
    forecasts: list[ForwardForecast], outcomes: dict[str, ForecastOutcome]
) -> PerformanceBreakdown:
    breakdowns = compute_performance(forecasts, outcomes)
    if breakdowns:
        return breakdowns[0]
    return PerformanceBreakdown(
        group="all",
        forecast_count=0,
        active_count=0,
        resolved_count=0,
        abstained_count=0,
        correct_count=0,
        incorrect_count=0,
        neutral_count=0,
        directional_accuracy=None,
        average_forward_return_percent=None,
        average_mfe_atr=None,
        average_mae_atr=None,
        coverage_rate=None,
        abstention_rate=None,
    )


def by_symbol(forecasts, outcomes) -> list[PerformanceBreakdown]:
    return compute_performance(forecasts, outcomes, lambda f: f.symbol)


def by_timeframe(forecasts, outcomes) -> list[PerformanceBreakdown]:
    return compute_performance(forecasts, outcomes, lambda f: f.timeframe)


def by_setup_type(forecasts, outcomes) -> list[PerformanceBreakdown]:
    return compute_performance(forecasts, outcomes, lambda f: f.setup_type or "none")


def by_catalyst_category(forecasts, outcomes) -> list[PerformanceBreakdown]:
    return compute_performance(forecasts, outcomes, lambda f: f.catalyst_category or "none")


def by_evidence_quality(forecasts, outcomes) -> list[PerformanceBreakdown]:
    return compute_performance(forecasts, outcomes, lambda f: f.evidence_quality.value)


def by_origin(forecasts, outcomes) -> list[PerformanceBreakdown]:
    return compute_performance(forecasts, outcomes, lambda f: f.origin.value)


def by_horizon(forecasts, outcomes) -> list[PerformanceBreakdown]:
    return compute_performance(forecasts, outcomes, lambda f: str(f.forecast_horizon_bars))
