"""Long-Term Research phone-push delivery -- reuses the SAME Pushover
account/encryption infrastructure as the Decision Engine's short-term
push (app.alerts.push, app.notifications.pushover,
app.notifications.secret_crypto) but is otherwise fully independent:
there is no shared eligibility gate, no shared DecisionPlan/AlertEvent
dependency, and no shared dispatch function -- a long-term research
transition is never derived from, or confused with, a short-term
ENTRY_CONDITIONS_MET alert.

Per spec, a push is sent to a user only when BOTH:
1. That symbol's research_state TRANSITIONED into one of
   app.long_term_research.schemas.PUSH_WORTHY_STATES on THIS run (the
   caller, app.long_term_research.service, decides this by comparing
   against the most recent prior snapshot -- this module has no opinion
   on "transition" at all, it only ever sends what it's told to).
2. That specific user has long_term_push_enabled AND their own Pushover
   key configured (app.long_term_research.repository).

Like app.alerts.push.dispatch_push_notifications, this function never
raises: any failure anywhere inside is caught, logged (without secrets),
and swallowed, because a Pushover outage must never corrupt or block the
already-persisted research snapshot (persisted by the caller BEFORE this
function is ever invoked -- see app.long_term_research.service)."""

from __future__ import annotations

import logging
from typing import Callable, Optional
from uuid import UUID

from app.config import Settings, get_settings
from app.decision_engine.ai_brief import contains_banned_language
from app.long_term_research.repository import LongTermResearchRepository
from app.long_term_research.schemas import LongTermResearchResult
from app.notifications.pushover import PushoverMessage, PushoverProvider
from app.notifications.secret_crypto import decrypt_secret

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[str, str], PushoverProvider]


def _default_provider_factory(app_token: str, user_key: str) -> PushoverProvider:
    return PushoverProvider(app_token, user_key)


def render_long_term_push_message(result: LongTermResearchResult) -> PushoverMessage:
    state_title = result.research_state.value.replace("_", " ").title()
    lines = []
    if result.price is not None:
        lines.append(f"Price: ${result.price:,.2f}")
    lines.append(f"Research state: {result.research_state.value.replace('_', ' ')}")
    lines.append(f"Evidence quality: {result.evidence_quality.value.replace('_', ' ').title()}")
    if result.factors.limited_history:
        lines.append("History: LIMITED")
    lines.append(f"Reason: {result.reason}")
    message_text = "\n".join(lines)

    title = f"{result.symbol} — {state_title}"
    violations = contains_banned_language(f"{title} {message_text}")
    if violations:
        raise ValueError(
            f"Long-term push message failed banned-language check: {violations}"
        )
    return PushoverMessage(title=title, message=message_text)


def dispatch_long_term_research_push(
    repository: LongTermResearchRepository,
    result: LongTermResearchResult,
    candidate_user_ids: list[UUID],
    *,
    settings: Optional[Settings] = None,
    provider_factory: Optional[ProviderFactory] = None,
) -> None:
    try:
        _dispatch(
            repository, result, candidate_user_ids, settings=settings, provider_factory=provider_factory
        )
    except Exception:  # noqa: BLE001 -- deliberate: delivery failure must never propagate
        logger.exception("Long-term research push dispatch failed for symbol=%s", result.symbol)


def _dispatch(
    repository: LongTermResearchRepository,
    result: LongTermResearchResult,
    candidate_user_ids: list[UUID],
    *,
    settings: Optional[Settings],
    provider_factory: Optional[ProviderFactory],
) -> None:
    settings = settings or get_settings()
    if (
        not settings.push_notifications_enabled
        or not settings.pushover_app_token
        or not settings.pushover_key_encryption_key
    ):
        return

    factory = provider_factory or _default_provider_factory
    message: Optional[PushoverMessage] = None

    for user_id in candidate_user_ids:
        if not repository.get_long_term_push_enabled(user_id):
            continue
        encrypted_key = repository.get_user_pushover_key_encrypted(user_id)
        if not encrypted_key:
            continue
        user_key = decrypt_secret(encrypted_key, encryption_key=settings.pushover_key_encryption_key)
        if not user_key:
            continue

        if message is None:
            message = render_long_term_push_message(result)

        provider = factory(settings.pushover_app_token, user_key)
        try:
            send_result = provider.send(message)
        finally:
            provider.close()

        logger.info(
            "long-term research push dispatch user=%s symbol=%s state=%s success=%s error=%s",
            user_id,
            result.symbol,
            result.research_state.value,
            send_result.success,
            send_result.error,
        )
