"""AlertService: the only place an AlertEvent is ever constructed (§2/§32).
Consumes deterministic facts already produced elsewhere (a DecisionTransition,
a flipped DecisionCondition, a freshness/stream-health change) and never
invents new evidence -- it just packages an existing fact into an immutable,
deduplicated, persisted record.

Every alert-producing method here funnels through `_record`, which is the
one place preference-gating, banned-language checking, and dedup/persist
happen -- so no caller can accidentally bypass any of the three.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.alerts.dedup import condition_dedup_key, transition_dedup_key
from app.alerts.repository import AlertRepository
from app.alerts.schemas import (
    DEFAULT_ALERT_PREFERENCES,
    DEFAULT_SEVERITY_BY_ALERT_TYPE,
    AlertEvent,
    AlertOrigin,
    AlertType,
)
from app.decision_engine.ai_brief import contains_banned_language
from app.decision_engine.schemas import DecisionPlan, DecisionState, DecisionTransition

PIPELINE_VERSION = "1.0"

# DecisionTransition.to_state -> AlertType, for the transitions that are
# alert-worthy per §3. ABSTAIN and the transient DETECTED state produce no
# alert -- an abstained setup is not something the user needs pushed at
# them (the Decision Scanner still surfaces it passively, see §36/§37).
TRANSITION_ALERT_TYPE_BY_STATE: dict[DecisionState, AlertType] = {
    DecisionState.EVALUATING: AlertType.PLAN_CREATED,
    DecisionState.WATCHING: AlertType.WATCHING,
    DecisionState.ENTRY_CONDITIONS_MET: AlertType.ENTRY_CONDITIONS_MET,
    DecisionState.ACTIVE_THESIS: AlertType.THESIS_ACTIVATED,
    DecisionState.THESIS_STRENGTHENING: AlertType.THESIS_STRENGTHENING,
    DecisionState.THESIS_WEAKENING: AlertType.THESIS_WEAKENING,
    DecisionState.INVALIDATED: AlertType.INVALIDATED,
    DecisionState.EXIT_CONDITIONS_MET: AlertType.EXIT_CONDITIONS_MET,
    DecisionState.EXPIRED: AlertType.EXPIRED,
}

_TITLE_BY_ALERT_TYPE: dict[AlertType, str] = {
    AlertType.PLAN_CREATED: "Plan created",
    AlertType.WATCHING: "Watching",
    AlertType.ENTRY_CONDITIONS_MET: "Entry conditions met",
    AlertType.THESIS_ACTIVATED: "Thesis activated",
    AlertType.THESIS_STRENGTHENING: "Thesis strengthening",
    AlertType.THESIS_WEAKENING: "Thesis weakening",
    AlertType.INVALIDATED: "Invalidated",
    AlertType.EXIT_CONDITIONS_MET: "Exit conditions met",
    AlertType.EXPIRED: "Expired",
}


def transition_alert_type(transition: DecisionTransition) -> Optional[AlertType]:
    return TRANSITION_ALERT_TYPE_BY_STATE.get(transition.to_state)


@dataclass(frozen=True)
class AlertEmittedEvent:
    """Pushed to listeners only when `_record` actually persisted a NEW
    row -- never on a preference-skip or a dedup hit against an existing
    alert, so a live WebSocket connection never sees the same alert twice
    just because the underlying evaluation happened to run again."""

    alert: AlertEvent


class AlertEventBus:
    """Just the pub/sub side of AlertService, pulled out so it can outlive
    any one AlertRepository/Session. A route-scoped or per-scan-pass
    AlertService is created fresh (same "new repository/session per
    operation" convention as ForecastMonitor/NewsMonitor -- see
    app.monitoring.service), but every one of those instances can share the
    SAME bus, so a WebSocket connection that registered a listener on the
    process-wide bus at startup keeps receiving events regardless of which
    short-lived AlertService instance actually emitted them."""

    def __init__(self) -> None:
        self._listeners: list["asyncio.Queue[AlertEmittedEvent]"] = []

    def add_listener(self) -> "asyncio.Queue[AlertEmittedEvent]":
        queue: "asyncio.Queue[AlertEmittedEvent]" = asyncio.Queue()
        self._listeners.append(queue)
        return queue

    def remove_listener(self, queue: "asyncio.Queue[AlertEmittedEvent]") -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def publish(self, event: AlertEmittedEvent) -> None:
        for queue in list(self._listeners):
            queue.put_nowait(event)


class AlertService:
    def __init__(
        self,
        repository: AlertRepository,
        now_fn=None,
        event_bus: Optional[AlertEventBus] = None,
    ) -> None:
        self._repository = repository
        self._now = now_fn or (lambda: datetime.now().astimezone())
        # Defaults to a private, instance-local bus so existing callers that
        # never pass one (every current test, every route-scoped usage) see
        # exactly the same behavior as before this existed. main.py's
        # background monitoring wiring is the one caller that passes a
        # shared, process-wide bus explicitly.
        self._event_bus = event_bus or AlertEventBus()

    def add_listener(self) -> "asyncio.Queue[AlertEmittedEvent]":
        return self._event_bus.add_listener()

    def remove_listener(self, queue: "asyncio.Queue[AlertEmittedEvent]") -> None:
        self._event_bus.remove_listener(queue)

    def _preference_enabled(self, alert_type: AlertType) -> bool:
        overrides = {p.alert_type: p.enabled for p in self._repository.get_preferences()}
        if alert_type in overrides:
            return overrides[alert_type]
        return DEFAULT_ALERT_PREFERENCES.get(alert_type, True)

    def _record(self, event: AlertEvent) -> Optional[AlertEvent]:
        if not self._preference_enabled(event.alert_type):
            return None
        violations = contains_banned_language(f"{event.title} {event.summary}")
        if violations:
            raise ValueError(f"AlertEvent text failed banned-language check: {violations}")
        stored, created = self._repository.record_event(event)
        if created:
            self._event_bus.publish(AlertEmittedEvent(alert=stored))
        return stored

    def emit_transition_alert(
        self,
        plan: DecisionPlan,
        transition: DecisionTransition,
        *,
        origin: AlertOrigin,
    ) -> Optional[AlertEvent]:
        """The single entry point for turning a real DecisionTransition into
        an AlertEvent (§2/§23/§24). Reuses the transition's own reason text
        verbatim as the deterministic "why" -- this package invents nothing."""
        alert_type = transition_alert_type(transition)
        if alert_type is None:
            return None

        dedup_key = transition_dedup_key(plan.decision_plan_id, transition.transition_id, alert_type)
        event = AlertEvent(
            alert_id=str(uuid.uuid4()),
            symbol=plan.symbol,
            decision_plan_id=plan.decision_plan_id,
            setup_id=plan.setup_id,
            alert_type=alert_type,
            severity=DEFAULT_SEVERITY_BY_ALERT_TYPE[alert_type],
            title=_TITLE_BY_ALERT_TYPE[alert_type],
            summary=transition.reason,
            previous_state=transition.from_state.value if transition.from_state else None,
            current_state=transition.to_state.value,
            occurred_at=transition.occurred_at,
            evaluated_at=transition.as_of,
            trigger_condition_ids=transition.trigger_condition_ids,
            evidence_refs=transition.evidence_refs,
            transition_id=transition.transition_id,
            timeframe=plan.timeframe.value,
            setup_type=plan.setup_type.value,
            direction=plan.direction.value,
            research_status=[r.value for r in plan.research_status],
            ranking_gate_status=plan.ranking_gate_status,
            dedup_key=dedup_key,
            origin=origin,
            pipeline_version=PIPELINE_VERSION,
            created_at=self._now(),
        )
        return self._record(event)

    def emit_condition_alert(
        self,
        *,
        symbol: str,
        alert_type: AlertType,
        identity: str,
        title: str,
        summary: str,
        source_timestamp: datetime,
        origin: AlertOrigin,
        decision_plan_id: Optional[str] = None,
        provider: Optional[str] = None,
        data_freshness_state: Optional[str] = None,
    ) -> Optional[AlertEvent]:
        """Non-transition alerts (§3): condition PASSED/FAILED, conflict
        added/removed, catalyst reclassification, data staleness/recovery,
        stream connect/disconnect. `identity` disambiguates within
        (symbol, alert_type) -- see app.alerts.dedup.condition_dedup_key."""
        dedup_key = condition_dedup_key(symbol, alert_type, identity, source_timestamp)
        event = AlertEvent(
            alert_id=str(uuid.uuid4()),
            symbol=symbol,
            decision_plan_id=decision_plan_id,
            alert_type=alert_type,
            severity=DEFAULT_SEVERITY_BY_ALERT_TYPE[alert_type],
            title=title,
            summary=summary,
            occurred_at=source_timestamp,
            source_timestamp=source_timestamp,
            evaluated_at=self._now(),
            provider=provider,
            data_freshness_state=data_freshness_state,
            dedup_key=dedup_key,
            origin=origin,
            pipeline_version=PIPELINE_VERSION,
            created_at=self._now(),
        )
        return self._record(event)
