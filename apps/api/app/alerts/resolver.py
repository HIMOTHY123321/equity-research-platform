"""Phase 14.1 (§33): the one and only place future data may enter the
alerts package -- mirroring the exact discipline
app.forecasting.resolver/app.research.outcomes already established (ADR
0008). An AlertEvent is never rewritten; this always produces a brand-new,
separate, immutable AlertOutcome linked by `alert_id`.

Reuses app.research.outcomes' pure horizon/excursion math verbatim
(`forward_candles`, `compute_horizon_outcomes`, `compute_excursion`) --
this module does not reimplement bar-return or MFE/MAE arithmetic, it only
adapts a DecisionPlan's own direction/activation evidence and an
AlertEvent's own transition history into the same inputs
app.setup_detection outcomes already use. "Time to invalidation"/"time to
exit" are read off the Decision Engine's own already-persisted, later
transitions for the same plan -- never recomputed independently, so the
Decision Engine's transition timing stays the single source of truth.

The live Decision Engine and AlertService never call anything in this
module -- only a resolver pass (see app.monitoring.service's periodic
call) does, and only well after the alert's own occurred_at.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from app.alerts.prospective import is_prospective_eligible
from app.alerts.repository import AlertRepository
from app.alerts.schemas import AlertEvent, AlertHorizonOutcome, AlertOrigin, AlertOutcome
from app.decision_engine.repository import DecisionEngineRepository
from app.decision_engine.schemas import DecisionState
from app.market_data.provider import MarketDataProvider
from app.research.outcomes import compute_excursion, compute_horizon_outcomes, forward_candles
from app.schemas.market_data import Timeframe

_HORIZONS = (1, 3, 5, 10, 20)
_MAX_HORIZON = max(_HORIZONS)

PIPELINE_VERSION = "1.0"


def _outcome_id(alert_id: str, resolved_at: datetime) -> str:
    digest_source = f"{alert_id}|{resolved_at.isoformat()}"
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]


def _bars_until(future_candles, target_ts: datetime) -> Optional[int]:
    for idx, candle in enumerate(future_candles):
        if candle.timestamp >= target_ts:
            return idx + 1
    return None


def resolve_alert_outcome(
    alert: AlertEvent,
    decision_repository: DecisionEngineRepository,
    alert_repository: AlertRepository,
    market_provider: MarketDataProvider,
    *,
    now: Optional[datetime] = None,
) -> Optional[AlertOutcome]:
    """Returns None whenever the alert isn't (yet, or ever) resolvable --
    never persists a partial/insufficient-data attempt (same rule as
    resolve_forecast: a too-early resolve pass must never permanently lock
    an alert out of resolving later). Callers should simply try again on a
    later pass; this function is idempotent and side-effect-free by
    itself -- persisting the result is the caller's job via
    AlertRepository.save_outcome, which is itself resolve-once."""
    resolved_at = now or datetime.now(timezone.utc)

    if not is_prospective_eligible(alert, decision_repository):
        return None
    if alert_repository.get_outcome_for_alert(alert.alert_id) is not None:
        return None  # already resolved -- never re-resolved (§Phase-14.1-5)

    plan = decision_repository.get_plan(alert.decision_plan_id)
    if plan is None or alert.timeframe is None:
        return None

    all_candles = market_provider.get_candles(alert.symbol, Timeframe(alert.timeframe), limit=50_000)
    future = forward_candles(all_candles, alert.occurred_at)
    if len(future) < _MAX_HORIZON:
        return None  # not enough future data yet -- try again later, never persisted

    past_or_equal = [c for c in all_candles if c.timestamp <= alert.occurred_at]
    if not past_or_equal:
        return None
    base_candle = max(past_or_equal, key=lambda c: c.timestamp)
    base_price = base_candle.close

    atr = plan.activation_snapshot.atr if plan.activation_snapshot is not None else None

    horizon_outcomes = compute_horizon_outcomes(future, base_price, plan.direction, _HORIZONS)
    horizons = {h.horizon_bars: h for h in horizon_outcomes}
    mfe = compute_excursion(future, base_price, plan.direction, atr, favorable=True)
    mae = compute_excursion(future, base_price, plan.direction, atr, favorable=False)

    bars_to_invalidation = None
    bars_to_exit = None
    for transition in decision_repository.list_transitions(alert.decision_plan_id):
        if transition.occurred_at <= alert.occurred_at:
            continue
        if transition.to_state == DecisionState.INVALIDATED and bars_to_invalidation is None:
            bars_to_invalidation = _bars_until(future, transition.occurred_at)
        elif transition.to_state == DecisionState.EXIT_CONDITIONS_MET and bars_to_exit is None:
            bars_to_exit = _bars_until(future, transition.occurred_at)

    return AlertOutcome(
        outcome_id=_outcome_id(alert.alert_id, resolved_at),
        alert_id=alert.alert_id,
        symbol=alert.symbol,
        decision_plan_id=alert.decision_plan_id,
        resolved_at=resolved_at,
        resolution_as_of=future[_MAX_HORIZON - 1].timestamp,
        return_1_bar_percent=horizons[1].directional_return_percent,
        return_3_bar_percent=horizons[3].directional_return_percent,
        return_5_bar_percent=horizons[5].directional_return_percent,
        return_10_bar_percent=horizons[10].directional_return_percent,
        return_20_bar_percent=horizons[20].directional_return_percent,
        mfe_atr=mfe.atr,
        mfe_bars_until=mfe.bars_until,
        mae_atr=mae.atr,
        mae_bars_until=mae.bars_until,
        bars_to_invalidation=bars_to_invalidation,
        bars_to_exit=bars_to_exit,
        bars_to_favorable_excursion=mfe.bars_until,
        bars_to_adverse_excursion=mae.bars_until,
        pipeline_version=PIPELINE_VERSION,
    )


def resolve_alert_horizon_outcomes(
    alert: AlertEvent,
    decision_repository: DecisionEngineRepository,
    alert_repository: AlertRepository,
    market_provider: MarketDataProvider,
    *,
    now: Optional[datetime] = None,
) -> list[AlertHorizonOutcome]:
    """Phase 15 per-horizon resolution: unlike resolve_alert_outcome (which
    blocks on the full 20-bar window), each of the 1/3/5/10/20-bar horizons
    resolves the instant ITS OWN future bars exist -- a symbol with 6 bars
    of new data since the alert can already have its 1/3/5-bar horizons
    resolved while 10/20 remain pending. Already-resolved horizons (per
    alert_repository.get_horizon_outcomes_for_alert) are skipped, so this
    is safe to call repeatedly as more bars accumulate. Returns only the
    NEWLY resolvable horizons for this call; persisting them is the
    caller's job via AlertRepository.save_horizon_outcome (itself
    resolve-once per (alert_id, horizon_bars))."""
    resolved_at = now or datetime.now(timezone.utc)

    if not is_prospective_eligible(alert, decision_repository):
        return []

    plan = decision_repository.get_plan(alert.decision_plan_id)
    if plan is None or alert.timeframe is None:
        return []

    already_resolved = {
        outcome.horizon_bars for outcome in alert_repository.get_horizon_outcomes_for_alert(alert.alert_id)
    }
    pending_horizons = [h for h in _HORIZONS if h not in already_resolved]
    if not pending_horizons:
        return []

    all_candles = market_provider.get_candles(alert.symbol, Timeframe(alert.timeframe), limit=50_000)
    future = forward_candles(all_candles, alert.occurred_at)

    past_or_equal = [c for c in all_candles if c.timestamp <= alert.occurred_at]
    if not past_or_equal:
        return []
    base_candle = max(past_or_equal, key=lambda c: c.timestamp)
    base_price = base_candle.close

    resolvable = [h for h in pending_horizons if len(future) >= h]
    if not resolvable:
        return []  # no newly-resolvable horizon yet -- try again later, never persisted

    horizon_outcomes = compute_horizon_outcomes(future, base_price, plan.direction, resolvable)
    outcomes: list[AlertHorizonOutcome] = []
    for horizon_outcome in horizon_outcomes:
        horizon_bars = horizon_outcome.horizon_bars
        outcome_id = _outcome_id(f"{alert.alert_id}|{horizon_bars}", resolved_at)
        outcomes.append(
            AlertHorizonOutcome(
                outcome_id=outcome_id,
                alert_id=alert.alert_id,
                symbol=alert.symbol,
                decision_plan_id=alert.decision_plan_id,
                horizon_bars=horizon_bars,
                resolved_at=resolved_at,
                resolution_as_of=future[horizon_bars - 1].timestamp,
                return_percent=horizon_outcome.directional_return_percent,
                pipeline_version=PIPELINE_VERSION,
            )
        )
    return outcomes


def resolve_pending_horizon_outcomes(
    alert_repository: AlertRepository,
    decision_repository: DecisionEngineRepository,
    market_provider: MarketDataProvider,
    *,
    now: Optional[datetime] = None,
) -> list[AlertHorizonOutcome]:
    """The per-horizon counterpart of resolve_pending_outcomes: every
    LIVE_PROSPECTIVE alert with at least one unresolved horizon is
    attempted; a symbol whose 20-bar horizon isn't ready yet still gets its
    1/3/5/10-bar horizons persisted as soon as they're independently
    available. Safe across process restarts and concurrent passes -- each
    (alert_id, horizon_bars) resolves at most once (save_horizon_outcome's
    own exactly-once guarantee)."""
    resolved: list[AlertHorizonOutcome] = []
    candidates = alert_repository.list_events(origin=AlertOrigin.LIVE_PROSPECTIVE.value, limit=100_000)
    for alert in candidates:
        outcomes = resolve_alert_horizon_outcomes(
            alert, decision_repository, alert_repository, market_provider, now=now
        )
        for outcome in outcomes:
            stored, created = alert_repository.save_horizon_outcome(outcome)
            if created:
                resolved.append(stored)
    return resolved


def resolve_pending_outcomes(
    alert_repository: AlertRepository,
    decision_repository: DecisionEngineRepository,
    market_provider: MarketDataProvider,
    *,
    now: Optional[datetime] = None,
) -> list[AlertOutcome]:
    """The directly-testable core of a resolver pass (same shape as
    ForecastMonitor.scan_and_resolve_once): every LIVE_PROSPECTIVE alert
    without an outcome yet is attempted; insufficient-future-data ones are
    silently skipped (never persisted, tried again next pass) and already-
    resolved ones are skipped by `save_outcome`'s own resolve-once
    guarantee -- so calling this repeatedly, including across a process
    restart, can never produce a duplicate resolved observation."""
    resolved: list[AlertOutcome] = []
    candidates = alert_repository.list_events(origin=AlertOrigin.LIVE_PROSPECTIVE.value, limit=100_000)
    for alert in candidates:
        if alert_repository.get_outcome_for_alert(alert.alert_id) is not None:
            continue
        outcome = resolve_alert_outcome(
            alert, decision_repository, alert_repository, market_provider, now=now
        )
        if outcome is None:
            continue
        stored, created = alert_repository.save_outcome(outcome)
        if created:
            resolved.append(stored)
    return resolved
