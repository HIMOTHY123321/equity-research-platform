"""Phase 12 (#O/#P): the Forward Validation Gate -- a *separate* gate from,
and never a replacement for, Phase 9's RANKING GATE (ADR 0012, still FAIL
and still binding). Criteria are fixed and versioned before results are
observed (`GATE_V1`); changing a threshold always means defining a new
`gate_version`, never editing an existing one's stored criteria -- see
app.forecasting.repository.save_gate_version, which is idempotent/immutable
the same way every other repository in this codebase is.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.forecasting.baselines import compute_baselines
from app.forecasting.metrics import overall_performance
from app.forecasting.schemas import ForecastOutcome, ForwardForecast

GATE_VERSION = "v1"


class GateDecision(str, Enum):
    NOT_ENOUGH_DATA = "not_enough_data"
    FAIL = "fail"
    PROMISING = "promising"
    PASS = "pass"


@dataclass(frozen=True)
class GateCriteria:
    min_prospective_forecast_count: int = 30
    min_independent_resolved_episodes: int = 20
    min_accuracy_margin_over_baseline_pp: float = 5.0
    max_single_symbol_share: float = 0.40
    max_single_time_bucket_share: float = 0.60
    max_abstention_rate: float = 0.80


GATE_V1_CRITERIA = GateCriteria()


@dataclass(frozen=True)
class GateEvaluation:
    gate_version: str
    decision: GateDecision
    reasons: list[str] = field(default_factory=list)
    forecast_count: int = 0
    resolved_count: int = 0
    independent_episode_estimate: int = 0
    accuracy: Optional[float] = None
    best_baseline_accuracy: Optional[float] = None
    best_baseline_name: Optional[str] = None
    abstention_rate: Optional[float] = None
    max_symbol_share: Optional[float] = None
    max_time_bucket_share: Optional[float] = None


def _independent_episode_estimate(forecasts: list[ForwardForecast]) -> int:
    """Deliberately approximate, and labeled as such: one (symbol, ISO
    calendar week) bucket counts as one independent episode -- a coarse but
    honest proxy for "non-overlapping in time per symbol," not a claim of
    the same rigor as app.research_intelligence.episodes' setup-level
    grouping (which operates on a different object entirely)."""
    buckets = {(f.symbol, f.market_as_of.isocalendar()[:2]) for f in forecasts}
    return len(buckets)


def _max_share(counter: Counter) -> Optional[float]:
    total = sum(counter.values())
    if total == 0:
        return None
    return max(counter.values()) / total


def evaluate_gate(
    forecasts: list[ForwardForecast],
    outcomes: dict[str, ForecastOutcome],
    criteria: GateCriteria = GATE_V1_CRITERIA,
    gate_version: str = GATE_VERSION,
) -> GateEvaluation:
    prospective = [f for f in forecasts if f.run_mode.value == "prospective"]
    resolved_outcomes = {
        f.forecast_id: outcomes[f.forecast_id] for f in prospective if f.forecast_id in outcomes
    }
    independent_episodes = _independent_episode_estimate(
        [f for f in prospective if f.forecast_id in resolved_outcomes]
    )

    if (
        len(prospective) < criteria.min_prospective_forecast_count
        or independent_episodes < criteria.min_independent_resolved_episodes
    ):
        return GateEvaluation(
            gate_version=gate_version,
            decision=GateDecision.NOT_ENOUGH_DATA,
            reasons=[
                f"{len(prospective)} prospective forecast(s) "
                f"(need {criteria.min_prospective_forecast_count}); "
                f"{independent_episodes} independent resolved episode(s) "
                f"(need {criteria.min_independent_resolved_episodes})."
            ],
            forecast_count=len(prospective),
            resolved_count=len(resolved_outcomes),
            independent_episode_estimate=independent_episodes,
        )

    overall = overall_performance(prospective, resolved_outcomes)
    baselines = [b for b in compute_baselines(prospective, resolved_outcomes) if b.accuracy is not None]
    best_baseline = max(baselines, key=lambda b: b.accuracy, default=None)

    resolved_prospective = [f for f in prospective if f.forecast_id in resolved_outcomes]
    symbol_share = _max_share(Counter(f.symbol for f in resolved_prospective))
    bucket_share = _max_share(
        Counter((f.market_as_of.year, f.market_as_of.month) for f in resolved_prospective)
    )
    abstention_rate = overall.abstention_rate

    reasons: list[str] = []
    if abstention_rate is not None and abstention_rate > criteria.max_abstention_rate:
        reasons.append(f"Abstention rate {abstention_rate:.0%} exceeds {criteria.max_abstention_rate:.0%}.")
    if symbol_share is not None and symbol_share > criteria.max_single_symbol_share:
        reasons.append(
            f"Single-symbol share {symbol_share:.0%} exceeds {criteria.max_single_symbol_share:.0%}."
        )
    if bucket_share is not None and bucket_share > criteria.max_single_time_bucket_share:
        reasons.append(
            f"Single-time-bucket share {bucket_share:.0%} exceeds "
            f"{criteria.max_single_time_bucket_share:.0%}."
        )

    if reasons:
        decision = GateDecision.FAIL
    elif overall.directional_accuracy is None or best_baseline is None:
        decision = GateDecision.NOT_ENOUGH_DATA
        reasons.append("Accuracy or baseline could not be computed from the resolved sample.")
    else:
        margin_pp = (overall.directional_accuracy - best_baseline.accuracy) * 100
        if margin_pp >= criteria.min_accuracy_margin_over_baseline_pp:
            decision = GateDecision.PASS
        elif margin_pp > 0:
            decision = GateDecision.PROMISING
            reasons.append(
                f"Accuracy beats best baseline ({best_baseline.name}) by only {margin_pp:.1f}pp "
                f"(need {criteria.min_accuracy_margin_over_baseline_pp:.1f}pp)."
            )
        else:
            decision = GateDecision.FAIL
            reasons.append(
                f"Accuracy does not beat best baseline ({best_baseline.name}): {margin_pp:.1f}pp margin."
            )

    return GateEvaluation(
        gate_version=gate_version,
        decision=decision,
        reasons=reasons,
        forecast_count=len(prospective),
        resolved_count=len(resolved_outcomes),
        independent_episode_estimate=independent_episodes,
        accuracy=overall.directional_accuracy,
        best_baseline_accuracy=best_baseline.accuracy if best_baseline else None,
        best_baseline_name=best_baseline.name if best_baseline else None,
        abstention_rate=abstention_rate,
        max_symbol_share=symbol_share,
        max_time_bucket_share=bucket_share,
    )
