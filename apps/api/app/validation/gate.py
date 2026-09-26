"""Phase 15 §26/§27/§28: the Forward Validation Gate for Decision/Alert
signals -- a *new*, separately-versioned gate, distinct from
`app.forecasting.gate` (which is forecast-scoped) and from the Phase 9
RANKING GATE (ADR 0012, still FAIL, still binding, never touched by this
module). Same immutable-versioned-criteria + immutable-result-row pattern
as `app.forecasting.gate`, applied to `ProspectiveObservation`s instead of
`ForwardForecast`s.

A handful of successful alerts must never produce PASS (§27) -- criteria
require independent episode breadth, symbol breadth, low concentration,
and cost-survival before PASS is even considered, and NOT_ENOUGH_DATA is
the correct, expected, potentially long-lived starting state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.schemas.market_data import Timeframe
from app.validation.cohort import build_cohort_statistics
from app.validation.concentration import detect_concentration
from app.validation.independence import episode_level_sample
from app.validation.schemas import ProspectiveObservation

SIGNAL_GATE_VERSION = "v1"

#: The horizon used to evaluate the gate -- 5 bars is the shortest horizon
#: with a meaningfully-sized independent sample in practice, per Phase
#: 15's own §41 decay analysis; other horizons remain visible in the
#: Validation Lab UI regardless of which one the gate itself checks.
GATE_HORIZON_BARS = 5


class SignalGateDecision(str, Enum):
    NOT_ENOUGH_DATA = "not_enough_data"
    FAIL = "fail"
    MIXED = "mixed"
    PASS = "pass"


@dataclass(frozen=True)
class SignalGateCriteria:
    min_independent_episodes: int = 20
    min_symbols: int = 5
    max_single_symbol_share: float = 0.40
    min_observation_days: int = 20
    max_cost_bps_for_survival: float = 5.0
    require_cost_survival: bool = True
    require_historical_agreement: bool = False


SIGNAL_GATE_V1_CRITERIA = SignalGateCriteria()


@dataclass(frozen=True)
class SignalGateEvaluation:
    gate_version: str
    decision: SignalGateDecision
    reasons: list[str] = field(default_factory=list)

    raw_n: int = 0
    independent_episode_count: int = 0
    purged_n: int = 0
    symbol_count: int = 0
    observation_days: Optional[float] = None
    max_symbol_share: Optional[float] = None
    median_effect: Optional[float] = None
    cost_adjusted_effect_at_max_bps: Optional[float] = None


def evaluate_signal_gate(
    observations: list[ProspectiveObservation],
    timeframe: Timeframe,
    criteria: SignalGateCriteria = SIGNAL_GATE_V1_CRITERIA,
    gate_version: str = SIGNAL_GATE_VERSION,
    horizon_bars: int = GATE_HORIZON_BARS,
) -> SignalGateEvaluation:
    resolved = [o for o in observations if o.resolved]
    episodes = episode_level_sample(resolved)
    independent_episode_count = len(episodes)
    symbols = {o.symbol for o in resolved}
    symbol_count = len(symbols)

    observation_days: Optional[float] = None
    if resolved:
        timestamps = [o.alert_occurred_at for o in resolved]
        observation_days = (max(timestamps) - min(timestamps)).total_seconds() / 86400.0

    if (
        independent_episode_count < criteria.min_independent_episodes
        or symbol_count < criteria.min_symbols
        or observation_days is None
        or observation_days < criteria.min_observation_days
    ):
        return SignalGateEvaluation(
            gate_version=gate_version,
            decision=SignalGateDecision.NOT_ENOUGH_DATA,
            reasons=[
                f"{independent_episode_count} independent episode(s) "
                f"(need {criteria.min_independent_episodes}); "
                f"{symbol_count} symbol(s) (need {criteria.min_symbols}); "
                f"{observation_days if observation_days is not None else 0:.1f} observation day(s) "
                f"(need {criteria.min_observation_days})."
            ],
            raw_n=len(resolved),
            independent_episode_count=independent_episode_count,
            symbol_count=symbol_count,
            observation_days=observation_days,
        )

    stats = build_cohort_statistics("gate_cohort", resolved, horizon_bars, timeframe)
    concentration = detect_concentration(resolved)
    symbol_warning = next((w for w in concentration if w.dimension == "symbol"), None)
    max_symbol_share = symbol_warning.share if symbol_warning is not None else None

    cost_point = next(
        (p for p in stats.cost_sensitivity if p.cost_bps == criteria.max_cost_bps_for_survival), None
    )
    cost_adjusted_effect = cost_point.median_return_after_cost if cost_point is not None else None

    reasons: list[str] = []
    if max_symbol_share is not None and max_symbol_share > criteria.max_single_symbol_share:
        reasons.append(
            f"Single-symbol share {max_symbol_share:.0%} exceeds {criteria.max_single_symbol_share:.0%}."
        )
    if criteria.require_cost_survival and cost_adjusted_effect is not None and cost_adjusted_effect <= 0:
        reasons.append(
            f"Median effect does not survive an estimated {criteria.max_cost_bps_for_survival:.0f} bps "
            "cost assumption."
        )

    if reasons:
        decision = SignalGateDecision.FAIL
    elif stats.median is None:
        decision = SignalGateDecision.NOT_ENOUGH_DATA
        reasons.append("Median effect could not be computed from the resolved sample.")
    elif stats.median > 0 and (cost_adjusted_effect is None or cost_adjusted_effect > 0):
        decision = SignalGateDecision.PASS
    else:
        decision = SignalGateDecision.MIXED
        reasons.append("Effect direction/magnitude is not consistently favorable across checks.")

    return SignalGateEvaluation(
        gate_version=gate_version,
        decision=decision,
        reasons=reasons,
        raw_n=stats.raw_n,
        independent_episode_count=independent_episode_count,
        purged_n=stats.purged_n,
        symbol_count=symbol_count,
        observation_days=observation_days,
        max_symbol_share=max_symbol_share,
        median_effect=stats.median,
        cost_adjusted_effect_at_max_bps=cost_adjusted_effect,
    )
