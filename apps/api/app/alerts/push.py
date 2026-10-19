"""Phase 20/20.1: turns an already-persisted, deterministic AlertEvent
(plus the DecisionPlan it came from) into zero or more Pushover phone
notifications -- ONE per genuinely eligible user, each sent to THAT
user's own Pushover destination, never a shared/global one.

This module invents nothing: every field in a notification is read
verbatim off the DecisionPlan/DecisionCondition/AlertEvent the Decision
Engine and AlertService already produced (see app.decision_engine.schemas,
app.alerts.schemas) -- never AI-generated text, never a new evaluation.
`dispatch_push_notifications` is called from exactly one place
(AlertService._record, immediately after a transition alert is newly
persisted) so this is additive delivery, not a second alert engine.

Security review (Phase 20.1): the original design read a single GLOBAL
`PUSHOVER_USER_KEY` and sent at most one notification per AlertEvent,
regardless of which users were eligible. In a multi-user product that is
a genuine cross-user data leak -- User B's monitored-symbol alert would
ring User A's phone if User A happened to be the one with a key
configured. There is now NO global user key at all: `PUSHOVER_APP_TOKEN`
is the only global credential that identifies this application to
Pushover (not a destination); each user who opts in stores their OWN
Pushover User Key, encrypted at rest under a DEDICATED
`PUSHOVER_KEY_ENCRYPTION_KEY` (app.notifications.secret_crypto, Phase
20.2 -- deliberately separate from `secret_key`/JWT signing, so routine
session-secret rotation never silently makes stored Pushover keys
undecryptable). Dispatch loops over every eligible user and sends a
SEPARATE Pushover API call per user, using `(global app_token, that
user's own key)` -- a user with no key configured, or the server-wide
encryption key missing entirely, is simply skipped, never substituted
with anyone else's.

Eligibility, per candidate user, every layer independently necessary:
1. `event.origin == AlertOrigin.LIVE_PROSPECTIVE` -- dev fixtures and
   historical replay NEVER produce a real phone buzz (§35/§52's existing
   "origin is the mechanical enforcement of what's real" discipline,
   reused here rather than re-invented).
2. `DecisionState(event.current_state)` is one of PUSH_ELIGIBLE_STATES --
   read directly off the SAME deterministic field the Decision Engine
   state machine itself set; WATCHING/ACTIVE_THESIS/EXPIRED/ABSTAIN never
   reach here regardless of any other configuration.
3. Push is globally enabled and the app token is configured
   (`app.config.Settings`).
4. The user monitors this symbol (AlertRepository.list_subscribed_user_ids
   -- deliberately NOT filtered by that user's in-app alert-type
   preference, see that method's own docstring for why: push is its own
   channel/opt-in, independent of in-app muting, so a user can mute
   THESIS_STRENGTHENING in-app yet still receive a push for it, or vice
   versa).
5. That user has their OWN push preference on AND their own Pushover key
   configured.

Duplicate suppression is NOT reimplemented here -- it is inherited for
free from AlertEventRecord's existing dedup_key UNIQUE constraint
(app.alerts.repository.record_event): this function is only ever invoked
when `_record` just inserted a genuinely NEW row, so an unchanged state
(no new DecisionTransition, hence no new AlertEvent) can never reach this
module at all.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Callable, Optional
from uuid import UUID

from app.alerts.repository import AlertRepository
from app.alerts.schemas import AlertEvent, AlertOrigin
from app.config import Settings, get_settings
from app.decision_engine.schemas import (
    ConditionRole,
    ConditionType,
    DecisionCondition,
    DecisionPlan,
    DecisionState,
)
from app.live.config import LiveSessionState
from app.live.market_hours import current_live_session
from app.market_data.sessions import EXCHANGE_TZ
from app.notifications.pushover import PushoverMessage, PushoverProvider
from app.notifications.secret_crypto import decrypt_secret

logger = logging.getLogger(__name__)

# §6 of the spec: plain-English titles, keyed by the deterministic
# DecisionState itself (not AlertType) so WATCHING/ABSTAIN -- which never
# produce an AlertType/AlertEvent at all, see
# app.alerts.service.TRANSITION_ALERT_TYPE_BY_STATE -- still have a
# defined, testable label matching the spec's own table exactly.
PLAIN_ENGLISH_STATE_TITLE: dict[DecisionState, str] = {
    DecisionState.WATCHING: "Watching for an entry",
    DecisionState.ENTRY_CONDITIONS_MET: "Entry setup active",
    DecisionState.ACTIVE_THESIS: "Setup is active",
    DecisionState.THESIS_STRENGTHENING: "Setup getting stronger",
    DecisionState.THESIS_WEAKENING: "Risk increasing",
    DecisionState.EXIT_CONDITIONS_MET: "Exit conditions reached",
    DecisionState.INVALIDATED: "Setup failed",
    DecisionState.ABSTAIN: "Not enough evidence",
}

# Only these five transitions ever produce a phone notification -- every
# other DecisionState (including WATCHING and ABSTAIN, both of which have
# a label above purely for completeness/testability) never does, by
# construction: this set is checked before anything else below.
PUSH_ELIGIBLE_STATES = frozenset(
    {
        DecisionState.ENTRY_CONDITIONS_MET,
        DecisionState.THESIS_STRENGTHENING,
        DecisionState.THESIS_WEAKENING,
        DecisionState.INVALIDATED,
        DecisionState.EXIT_CONDITIONS_MET,
    }
)

_SESSION_LABEL: dict[LiveSessionState, str] = {
    LiveSessionState.PRE_MARKET: "Pre-market",
    LiveSessionState.REGULAR: "Regular session",
    LiveSessionState.AFTER_HOURS: "After hours",
    LiveSessionState.MARKET_CLOSED: "Market closed",
}

_PRICE_CONDITION_TYPES = frozenset(
    {
        ConditionType.PRICE_ABOVE,
        ConditionType.PRICE_BELOW,
        ConditionType.CLOSE_ABOVE,
        ConditionType.CLOSE_BELOW,
    }
)


def _all_conditions(plan: DecisionPlan) -> list[DecisionCondition]:
    return [
        *plan.entry_conditions,
        *plan.invalidation_conditions,
        *plan.exit_conditions,
        *plan.monitoring_conditions,
    ]


def _latest_known_price(plan: DecisionPlan, event: AlertEvent) -> Optional[float]:
    """Best-effort, deterministic-evidence-only price: prefers whichever
    price-type condition actually triggered THIS transition
    (`event.trigger_condition_ids`), falling back to the most recently
    evaluated price-type condition on the plan. Never a live quote lookup
    -- this module only ever reads fields already frozen on the plan/
    event, so it stays trivially unit-testable and introduces no new
    dependency on live market-data state."""
    conditions = _all_conditions(plan)
    triggering = [
        c
        for c in conditions
        if c.id in event.trigger_condition_ids
        and c.type in _PRICE_CONDITION_TYPES
        and c.actual_value is not None
    ]
    if triggering:
        return triggering[0].actual_value

    priced = [c for c in conditions if c.type in _PRICE_CONDITION_TYPES and c.actual_value is not None]
    if not priced:
        return None
    priced.sort(key=lambda c: c.evaluated_at or datetime.min.replace(tzinfo=None), reverse=True)
    return priced[0].actual_value


def _first_required_value(conditions: Iterable[DecisionCondition], role: ConditionRole) -> Optional[float]:
    for condition in conditions:
        if condition.role == role and condition.required_value is not None:
            return condition.required_value
    return None


def _setup_label(plan: DecisionPlan) -> str:
    text = plan.setup_type.value.replace("_", " ")
    return text[:1].upper() + text[1:]


def _format_et_timestamp(local_time: datetime) -> str:
    """Portable across platforms -- deliberately avoids `%-d`/`%-I`
    (glibc-only strftime extensions that raise on Windows, where this
    codebase's own tests and local dev run)."""
    hour12 = local_time.hour % 12 or 12
    return f"{local_time:%b} {local_time.day}, {local_time.year} {hour12}:{local_time:%M %p} ET"


class PushNotificationContent:
    """Pure value object -- every field traced back to a DecisionPlan/
    AlertEvent field in the docstring of whichever function built it."""

    __slots__ = (
        "ticker",
        "state_title",
        "price",
        "setup_label",
        "confirmation_level",
        "invalidation_level",
        "timestamp_et",
        "session_label",
        "research_url",
    )

    def __init__(
        self,
        *,
        ticker: str,
        state_title: str,
        price: Optional[float],
        setup_label: str,
        confirmation_level: Optional[float],
        invalidation_level: Optional[float],
        timestamp_et: str,
        session_label: str,
        research_url: Optional[str],
    ) -> None:
        self.ticker = ticker
        self.state_title = state_title
        self.price = price
        self.setup_label = setup_label
        self.confirmation_level = confirmation_level
        self.invalidation_level = invalidation_level
        self.timestamp_et = timestamp_et
        self.session_label = session_label
        self.research_url = research_url


def build_push_content(
    plan: DecisionPlan, event: AlertEvent, *, settings: Optional[Settings] = None
) -> PushNotificationContent:
    settings = settings or get_settings()
    state = DecisionState(event.current_state)
    local_time = event.occurred_at.astimezone(EXCHANGE_TZ)
    session = current_live_session(event.occurred_at)
    return PushNotificationContent(
        ticker=event.symbol,
        state_title=PLAIN_ENGLISH_STATE_TITLE.get(state, state.value),
        price=_latest_known_price(plan, event),
        setup_label=_setup_label(plan),
        confirmation_level=_first_required_value(plan.entry_conditions, ConditionRole.ENTRY),
        invalidation_level=_first_required_value(plan.invalidation_conditions, ConditionRole.INVALIDATION),
        timestamp_et=_format_et_timestamp(local_time),
        session_label=_SESSION_LABEL.get(session, session.value),
        research_url=f"{settings.app_url}/?symbol={event.symbol}" if settings.app_url else None,
    )


def render_push_message(content: PushNotificationContent) -> PushoverMessage:
    lines = [f"State: {content.state_title}"]
    if content.price is not None:
        lines.insert(0, f"Price: ${content.price:,.2f}")
    if content.setup_label:
        lines.append(f"Setup: {content.setup_label}")
    if content.confirmation_level is not None:
        lines.append(f"Confirmation: ${content.confirmation_level:,.2f}")
    if content.invalidation_level is not None:
        lines.append(f"Invalidation: ${content.invalidation_level:,.2f}")
    lines.append(f"{content.session_label} -- {content.timestamp_et}")
    return PushoverMessage(
        title=f"{content.ticker} — {content.state_title}",
        message="\n".join(lines),
        url=content.research_url,
        url_title="Open research" if content.research_url else None,
    )


def is_push_eligible_transition(event: AlertEvent) -> bool:
    """The two gates that depend only on the event itself (never on any
    user's own preference/destination) -- reused by both
    AlertService._record (to decide whether to bypass the in-app default
    for recording purposes) and this module's own dispatch below, so the
    two can never drift apart."""
    if event.origin != AlertOrigin.LIVE_PROSPECTIVE:
        return False
    try:
        state = DecisionState(event.current_state) if event.current_state else None
    except ValueError:
        return False
    return state in PUSH_ELIGIBLE_STATES


# A provider factory takes (app_token, this_user's_own_key) and returns
# something with a `.send(message)` -> PushoverSendResult and a
# `.close()` -- the real PushoverProvider by default, swappable in tests
# so no real network call is ever made and per-user sends can be told
# apart by which key they were constructed with.
ProviderFactory = Callable[[str, str], PushoverProvider]


def _default_provider_factory(app_token: str, user_key: str) -> PushoverProvider:
    return PushoverProvider(app_token, user_key)


def dispatch_push_notifications(
    repository: AlertRepository,
    event: AlertEvent,
    plan: DecisionPlan,
    subscribed_user_ids: list[UUID],
    *,
    settings: Optional[Settings] = None,
    provider_factory: Optional[ProviderFactory] = None,
) -> None:
    """Called from AlertService._record, only immediately after a
    transition-alert AlertEvent was genuinely newly persisted (never on a
    dedup hit, never for condition alerts). `subscribed_user_ids` is
    every user who monitors `event.symbol` -- see
    AlertRepository.list_subscribed_user_ids -- NOT the in-app-delivered
    set, since push is its own independent opt-in. Never raises -- any
    failure anywhere in here is caught, logged (without secrets), and
    swallowed, because a Pushover outage must never crash the Decision
    Engine or the monitoring loop that called into this (§8 of the
    spec)."""
    try:
        _dispatch(
            repository, event, plan, subscribed_user_ids, settings=settings, provider_factory=provider_factory
        )
    except Exception:  # noqa: BLE001 -- deliberate: delivery failure must never propagate
        logger.exception("Push notification dispatch failed for alert_id=%s", event.alert_id)


def _dispatch(
    repository: AlertRepository,
    event: AlertEvent,
    plan: DecisionPlan,
    subscribed_user_ids: list[UUID],
    *,
    settings: Optional[Settings],
    provider_factory: Optional[ProviderFactory],
) -> None:
    if not is_push_eligible_transition(event):
        return

    settings = settings or get_settings()
    if (
        not settings.push_notifications_enabled
        or not settings.pushover_app_token
        or not settings.pushover_key_encryption_key
    ):
        return

    factory = provider_factory or _default_provider_factory
    content: Optional[PushNotificationContent] = None
    message: Optional[PushoverMessage] = None

    for user_id in subscribed_user_ids:
        if not repository.get_user_push_enabled(user_id):
            continue
        encrypted_key = repository.get_user_pushover_key_encrypted(user_id)
        if not encrypted_key:
            continue  # this user alone is skipped -- never substitutes another user's key
        user_key = decrypt_secret(encrypted_key, encryption_key=settings.pushover_key_encryption_key)
        if not user_key:
            continue  # undecryptable (e.g. encryption key rotated) -- treat as "no key configured"

        if content is None:
            content = build_push_content(plan, event, settings=settings)
            message = render_push_message(content)

        provider = factory(settings.pushover_app_token, user_key)
        try:
            result = provider.send(message)
        finally:
            provider.close()

        logger.info(
            "push dispatch user=%s symbol=%s alert_id=%s state=%s success=%s error=%s",
            user_id,
            event.symbol,
            event.alert_id,
            event.current_state,
            result.success,
            result.error,
        )
        repository.record_push_delivery(user_id, event.alert_id, success=result.success, error=result.error)
