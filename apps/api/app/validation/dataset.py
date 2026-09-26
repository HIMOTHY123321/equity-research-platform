"""Phase 15 §1/§3: builds the prospective (and, separately, historical)
research datasets. Never mixes the two (§1) -- callers get two distinct
lists, never a merged one.

Reuses `app.alerts.prospective.is_prospective_eligible` verbatim as the
provenance gate -- this module adds no new eligibility rule of its own,
it only projects already-eligible AlertEvents (+ their resolved
AlertOutcome, when one exists) into a `ProspectiveObservation`.
"""

from __future__ import annotations

import hashlib

from app.alerts.prospective import is_prospective_eligible
from app.alerts.repository import AlertRepository
from app.alerts.resolver import _HORIZONS as _ALL_HORIZONS
from app.alerts.schemas import AlertEvent, AlertHorizonOutcome, AlertOrigin, AlertOutcome
from app.decision_engine.repository import DecisionEngineRepository
from app.validation.schemas import DatasetOrigin, ProspectiveObservation, ResolutionQuality

PIPELINE_VERSION = "1.0"


def _observation_id(alert_id: str) -> str:
    return hashlib.sha256(f"observation|{alert_id}".encode()).hexdigest()[:40]


def _horizon_returns(horizon_outcomes: list[AlertHorizonOutcome]) -> dict[int, float]:
    return {outcome.horizon_bars: outcome.return_percent for outcome in horizon_outcomes}


def _resolution_quality(
    horizon_outcomes: list[AlertHorizonOutcome],
) -> tuple[bool, ResolutionQuality]:
    """Phase 15 per-horizon resolution: `resolved` and `resolution_quality`
    are now derived from exactly which of the 1/3/5/10/20-bar horizons
    have independently resolved for this alert (never from the legacy
    all-or-nothing AlertOutcome). Zero resolved horizons is the normal,
    expected state for a recent alert; some-but-not-all is PARTIAL --
    never silently reported as fully resolved."""
    resolved_count = len(horizon_outcomes)
    if resolved_count == 0:
        return False, ResolutionQuality.INSUFFICIENT_FUTURE_DATA
    if resolved_count < len(_ALL_HORIZONS):
        return False, ResolutionQuality.PARTIAL
    return True, ResolutionQuality.VALID


def _volatility_regime(rvol: float | None) -> str | None:
    if rvol is None:
        return None
    if rvol < 1.0:
        return "low"
    if rvol < 2.0:
        return "normal"
    return "high"


def _market_regime(structure_by_timeframe: dict[str, str]) -> str | None:
    # Best-effort, sourced only from the plan's own already-persisted
    # ActivationSnapshot -- never fabricated, never recomputed here.
    return structure_by_timeframe.get("1d") or structure_by_timeframe.get("4h")


def _project(
    alert: AlertEvent,
    outcome: AlertOutcome | None,
    horizon_outcomes: list[AlertHorizonOutcome],
    decision_repository: DecisionEngineRepository,
) -> ProspectiveObservation:
    resolved, quality = _resolution_quality(horizon_outcomes)
    returns = _horizon_returns(horizon_outcomes)
    latest_resolved_at = max((h.resolved_at for h in horizon_outcomes), default=None)

    plan = decision_repository.get_plan(alert.decision_plan_id) if alert.decision_plan_id else None
    snapshot = plan.activation_snapshot if plan is not None else None

    return ProspectiveObservation(
        observation_id=_observation_id(alert.alert_id),
        alert_id=alert.alert_id,
        decision_plan_id=alert.decision_plan_id,
        transition_id=alert.transition_id,
        symbol=alert.symbol,
        setup_type=alert.setup_type,
        direction=alert.direction,
        timeframe=alert.timeframe,
        decision_state=alert.current_state,
        event_type=alert.alert_type.value,
        alert_occurred_at=alert.occurred_at,
        activated_at=snapshot.activated_at if snapshot is not None else None,
        resolved_at=latest_resolved_at,
        reference_price=snapshot.activation_price_reference if snapshot is not None else None,
        return_1=returns.get(1),
        return_3=returns.get(3),
        return_5=returns.get(5),
        return_10=returns.get(10),
        return_20=returns.get(20),
        mfe_atr=outcome.mfe_atr if outcome is not None else None,
        mae_atr=outcome.mae_atr if outcome is not None else None,
        time_to_mfe=outcome.mfe_bars_until if outcome is not None else None,
        time_to_mae=outcome.mae_bars_until if outcome is not None else None,
        time_to_invalidation=outcome.bars_to_invalidation if outcome is not None else None,
        time_to_exit=outcome.bars_to_exit if outcome is not None else None,
        market_regime=_market_regime(snapshot.structure_by_timeframe) if snapshot is not None else None,
        volatility_regime=_volatility_regime(snapshot.rvol) if snapshot is not None else None,
        catalyst_classification=snapshot.catalyst_label if snapshot is not None else None,
        research_status_at_event=list(plan.research_status) if plan is not None else [],
        ranking_gate_status_at_event=plan.ranking_gate_status if plan is not None else None,
        provider=alert.provider,
        source_timestamp=alert.source_timestamp,
        origin=DatasetOrigin.PROSPECTIVE,
        pipeline_version=PIPELINE_VERSION,
        resolved=resolved,
        resolution_quality=quality,
    )


def build_prospective_dataset(
    alert_repository: AlertRepository,
    decision_repository: DecisionEngineRepository,
    *,
    resolved_only: bool = False,
) -> list[ProspectiveObservation]:
    """The primary Phase 15 dataset (§1): every genuinely eligible
    LIVE_PROSPECTIVE AlertEvent, re-validated through
    `is_prospective_eligible` (never trusting a caller-supplied filter
    alone), projected into a `ProspectiveObservation`. Per-horizon returns
    (§ per-horizon resolution) come from AlertRepository.
    get_horizon_outcomes_for_alert and may be a strict subset of the 5
    horizons -- `resolved`/`resolution_quality` reflect exactly that
    (PARTIAL when some-but-not-all horizons have resolved). MFE/MAE/
    invalidation/exit timing still come from the legacy all-or-nothing
    AlertOutcome (only ever populated once the full 20-bar window
    completes). Unresolved observations are included by default (with
    `resolved=False`) so §62's "observation monitor" (unresolved/partial/
    resolved counts) has something to count -- pass `resolved_only=True`
    for statistics that must only ever see fully-resolved outcomes."""
    candidates = alert_repository.list_events(origin=AlertOrigin.LIVE_PROSPECTIVE.value, limit=100_000)
    observations: list[ProspectiveObservation] = []
    for alert in candidates:
        if not is_prospective_eligible(alert, decision_repository):
            continue
        outcome = alert_repository.get_outcome_for_alert(alert.alert_id)
        horizon_outcomes = alert_repository.get_horizon_outcomes_for_alert(alert.alert_id)
        observation = _project(alert, outcome, horizon_outcomes, decision_repository)
        if resolved_only and not observation.resolved:
            continue
        observations.append(observation)
    return observations
