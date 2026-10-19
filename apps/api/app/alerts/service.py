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
from datetime import datetime, timedelta
from typing import Optional

from app.alerts.dedup import DEFAULT_COOLDOWN, condition_dedup_key, transition_dedup_key
from app.alerts.push import dispatch_push_notifications, is_push_eligible_transition
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

    def _explicit_preference(self, alert_type: AlertType) -> Optional[bool]:
        """None when no operator override exists at all -- distinct from
        an explicit False, which must always be respected (§20.1: push
        never overrides an EXPLICIT disable, only the bare DEFAULT)."""
        overrides = {p.alert_type: p.enabled for p in self._repository.get_preferences()}
        return overrides.get(alert_type)

    def _preference_enabled(self, alert_type: AlertType) -> bool:
        explicit = self._explicit_preference(alert_type)
        if explicit is not None:
            return explicit
        return DEFAULT_ALERT_PREFERENCES.get(alert_type, True)

    def _record(self, event: AlertEvent, *, push_plan: Optional[DecisionPlan] = None) -> Optional[AlertEvent]:
        explicit = self._explicit_preference(event.alert_type)
        default = DEFAULT_ALERT_PREFERENCES.get(event.alert_type, True)
        globally_allowed = explicit if explicit is not None else default

        # Phase 20.1: a push-eligible, LIVE_PROSPECTIVE transition is
        # still recorded (so dedup applies and a user who explicitly
        # opted into push can still receive one) even when only the bare
        # DEFAULT -- never an explicit operator override -- would
        # otherwise block it. This never changes the in-app Alert Center
        # default for anyone: deliver_alert_to_subscribed_users below
        # still applies each user's OWN alert-type preference (which
        # defaults exactly the way it always has), and the event bus is
        # only published when something was actually delivered in-app or
        # the type is genuinely globally allowed -- see below.
        push_bypass = (
            explicit is None
            and not default
            and push_plan is not None
            and is_push_eligible_transition(event)
        )
        if not globally_allowed and not push_bypass:
            return None

        violations = contains_banned_language(f"{event.title} {event.summary}")
        if violations:
            raise ValueError(f"AlertEvent text failed banned-language check: {violations}")
        stored, created = self._repository.record_event(event)
        if created:
            # Phase 16.1 (§4/§15): fan out to every user who monitors this
            # symbol -- purely a per-user delivery/read-state row keyed off
            # this ONE already-persisted, never-duplicated AlertEventRecord.
            # Must run only on a genuine new row, never on a dedup hit,
            # same discipline as the event-bus publish above. This fan-out
            # still applies each user's own in-app alert-type preference
            # (unchanged default) -- a push-bypass never widens who sees
            # this in their Alert Center.
            delivered_user_ids = self._repository.deliver_alert_to_subscribed_users(stored)
            if globally_allowed or delivered_user_ids:
                self._event_bus.publish(AlertEmittedEvent(alert=stored))
            # Phase 20/20.1: phone-push delivery. `push_plan` is only ever
            # passed by emit_transition_alert below -- condition alerts
            # (data-staleness, stream health, etc.) are never push-
            # eligible in the first place (see
            # app.alerts.push.PUSH_ELIGIBLE_STATES), so there is nothing
            # for this to do for them regardless. Push candidates are
            # every user who monitors this symbol (NOT delivered_user_ids
            # -- push is its own opt-in, independent of each user's
            # in-app alert-type preference; see
            # AlertRepository.list_subscribed_user_ids). Dispatch itself
            # can never raise (see that module's own docstring) -- this
            # is purely additive delivery on top of the exactly-once
            # `created` guard above, never a second alert engine.
            if push_plan is not None:
                subscribed_user_ids = self._repository.list_subscribed_user_ids(stored.symbol)
                if subscribed_user_ids:
                    dispatch_push_notifications(self._repository, stored, push_plan, subscribed_user_ids)
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
        return self._record(event, push_plan=plan)

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
        cooldown: timedelta = DEFAULT_COOLDOWN,
    ) -> Optional[AlertEvent]:
        """Non-transition alerts (§3): condition PASSED/FAILED, conflict
        added/removed, catalyst reclassification, data staleness/recovery,
        stream connect/disconnect. `identity` disambiguates within
        (symbol, alert_type) -- see app.alerts.dedup.condition_dedup_key.
        `cooldown` defaults to the standard 1-hour repeated-poll cooldown;
        callers that already throttle on a genuine state TRANSITION (e.g.
        MonitoringService's freshness-transition detector) should pass a
        much shorter one -- the transition detector is the real throttle
        there, and the dedup key only needs to guard against re-emitting
        the exact same transition instant twice (a restart racing the same
        tick, concurrent evaluation), not collapse two real, separate
        episodes that happen to land in the same hour."""
        dedup_key = condition_dedup_key(symbol, alert_type, identity, source_timestamp, cooldown=cooldown)
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
