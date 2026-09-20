"""Phase 12 (#I): baseline comparisons. Forecast performance is measured
against these on the *same* resolved sample a real result is reported
against -- never compared to a different population. Every baseline reads
`ForecastOutcome.actual_value` (the resolver's own determination of what
actually happened, in the same closed vocabulary as `forecast_value`) --
never re-derives it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

from app.forecasting.schemas import ForecastOutcome, ForwardForecast


@dataclass(frozen=True)
class BaselineResult:
    name: str
    accuracy: Optional[float]
    sample_size: int


def _resolved_pairs(
    forecasts: list[ForwardForecast], outcomes: dict[str, ForecastOutcome]
) -> list[tuple[ForwardForecast, ForecastOutcome]]:
    """Only pairs with a real, comparable actual_value -- INSUFFICIENT_
    FUTURE_DATA/INVALIDATED rows (no actual_value) never enter a baseline
    denominator, same as they're excluded from directional accuracy."""
    pairs = []
    for forecast in forecasts:
        outcome = outcomes.get(forecast.forecast_id)
        if outcome is not None and outcome.actual_value is not None:
            pairs.append((forecast, outcome))
    return pairs


def _fixed_value_baseline(
    forecasts: list[ForwardForecast], outcomes: dict, name: str, fixed_value: str
) -> BaselineResult:
    """Accuracy of always guessing `fixed_value` against each pair's own
    resolved actual_value."""
    pairs = _resolved_pairs(forecasts, outcomes)
    if not pairs:
        return BaselineResult(name=name, accuracy=None, sample_size=0)
    correct = sum(1 for _f, outcome in pairs if outcome.actual_value == fixed_value)
    return BaselineResult(name=name, accuracy=correct / len(pairs), sample_size=len(pairs))


def _majority_class_baseline(
    forecasts: list[ForwardForecast], outcomes: dict, name: str, key: Callable[[ForwardForecast], str]
) -> BaselineResult:
    """Accuracy of always guessing the single most common *actual_value*
    within each `key`-defined group -- the generic "no real skill beyond
    the group's own base rate" comparator, usable for every category
    (same-symbol / setup-type / catalyst-category baselines are all this
    function with a different grouping key)."""
    pairs = _resolved_pairs(forecasts, outcomes)
    if not pairs:
        return BaselineResult(name=name, accuracy=None, sample_size=0)

    by_group: dict[str, list[tuple[ForwardForecast, ForecastOutcome]]] = {}
    for forecast, outcome in pairs:
        by_group.setdefault(key(forecast), []).append((forecast, outcome))

    total_correct = 0
    for group_pairs in by_group.values():
        majority_actual = Counter(o.actual_value for _f, o in group_pairs).most_common(1)[0][0]
        total_correct += sum(1 for _f, o in group_pairs if o.actual_value == majority_actual)

    return BaselineResult(name=name, accuracy=total_correct / len(pairs), sample_size=len(pairs))


def compute_baselines(
    forecasts: list[ForwardForecast], outcomes: dict[str, ForecastOutcome]
) -> list[BaselineResult]:
    direction_forecasts = [f for f in forecasts if f.forecast_category.value == "direction"]
    return [
        _fixed_value_baseline(direction_forecasts, outcomes, "always_up", "up"),
        _fixed_value_baseline(direction_forecasts, outcomes, "always_down", "down"),
        _fixed_value_baseline(direction_forecasts, outcomes, "no_change_flat", "flat_indeterminate"),
        _majority_class_baseline(forecasts, outcomes, "matched_unconditional", lambda f: "all"),
        _majority_class_baseline(forecasts, outcomes, "same_symbol_historical", lambda f: f.symbol),
        _majority_class_baseline(
            forecasts, outcomes, "forecast_category_baseline", lambda f: f.forecast_category.value
        ),
    ]
