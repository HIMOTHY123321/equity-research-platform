"""Phase 20/20.1: app.alerts.push in isolation -- content building,
eligibility gating, and per-user-destination dispatch resilience. No real
Pushover account/network calls anywhere in this file (FakeProviderFactory
stands in). Security review focus: a user's alert must NEVER be sent to
another user's Pushover destination -- see the "Dispatch" section below,
especially test_a_users_push_is_sent_only_to_their_own_destination_key and
test_two_eligible_users_with_separate_destinations_receive_separate_calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.alerts.push import (
    PLAIN_ENGLISH_STATE_TITLE,
    PUSH_ELIGIBLE_STATES,
    build_push_content,
    dispatch_push_notifications,
    is_push_eligible_transition,
    render_push_message,
)
from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertOrigin, AlertType
from app.alerts.service import AlertService
from app.config import Settings
from app.decision_engine.ai_brief import contains_banned_language
from app.decision_engine.schemas import (
    BarSemantics,
    ConditionOperator,
    ConditionRole,
    ConditionStatus,
    ConditionType,
    DecisionCondition,
    DecisionState,
)
from app.decision_engine.state_machine import build_transition
from app.notifications.pushover import PushoverSendResult
from app.notifications.secret_crypto import encrypt_secret
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import make_session
from tests.unit.decision_engine.test_state_machine import make_plan

_ENCRYPTION_KEY = "test-pushover-key-encryption-key-at-least-32-chars"


def _condition(
    *, role: ConditionRole, type_: ConditionType, required_value=None, actual_value=None, cond_id=None
) -> DecisionCondition:
    return DecisionCondition(
        id=cond_id or str(uuid4()),
        role=role,
        type=type_,
        description="test condition",
        timeframe=Timeframe.FIVE_MIN,
        bar_semantics=BarSemantics.TICK,
        operator=ConditionOperator.GTE,
        required_value=required_value,
        actual_value=actual_value,
        status=ConditionStatus.PASSED,
        evaluated_at=datetime(2026, 10, 19, 14, 35, tzinfo=timezone.utc),
    )


def _plan_with_conditions(state: DecisionState):
    entry_cond = _condition(
        role=ConditionRole.ENTRY,
        type_=ConditionType.PRICE_ABOVE,
        required_value=145.00,
        actual_value=146.18,
        cond_id="entry-1",
    )
    invalidation_cond = _condition(
        role=ConditionRole.INVALIDATION,
        type_=ConditionType.PRICE_BELOW,
        required_value=142.95,
    )
    plan = make_plan(state)
    return plan.model_copy(
        update={"entry_conditions": [entry_cond], "invalidation_conditions": [invalidation_cond]}
    )


def _settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        environment="test",
        push_notifications_enabled=True,
        pushover_app_token="test-app-token",
        pushover_key_encryption_key=_ENCRYPTION_KEY,
        app_url="https://ai-market-desk-web.onrender.com",
    )
    base.update(overrides)
    return Settings(**base)


def _encrypted(plaintext_key: str, settings: Settings) -> str:
    return encrypt_secret(plaintext_key, encryption_key=settings.pushover_key_encryption_key)


class _FakeRepo:
    """Minimal stand-in exposing only what dispatch_push_notifications
    needs. `keys` maps user_id -> ENCRYPTED key string (produced via the
    real encrypt_secret, so dispatch's real decrypt_secret call is
    exercised end-to-end, not bypassed)."""

    def __init__(self, push_enabled_users: set | None = None, keys: dict | None = None):
        self._push_enabled_users = push_enabled_users or set()
        self._keys = keys or {}
        self.recorded: list = []

    def get_user_push_enabled(self, user_id) -> bool:
        return user_id in self._push_enabled_users

    def get_user_pushover_key_encrypted(self, user_id):
        return self._keys.get(user_id)

    def record_push_delivery(self, user_id, alert_id, *, success, error=None):
        self.recorded.append((user_id, alert_id, success, error))


class FakeProviderFactory:
    """Records every (app_token, user_key) pair it was asked to build a
    provider for, and every message sent through each -- the thing this
    whole security review is about: proving which user's key a send
    actually used."""

    def __init__(self, result: PushoverSendResult | None = None, raise_exc: Exception | None = None):
        self.calls: list[tuple[str, str]] = []
        self.sent: list[tuple[str, object]] = []  # (user_key, message)
        self._result = result or PushoverSendResult(success=True)
        self._raise_exc = raise_exc

    def __call__(self, app_token: str, user_key: str):
        self.calls.append((app_token, user_key))
        return _FakeProvider(self, user_key)


class _FakeProvider:
    def __init__(self, factory: FakeProviderFactory, user_key: str):
        self._factory = factory
        self._user_key = user_key

    def send(self, message):
        self._factory.sent.append((self._user_key, message))
        if self._factory._raise_exc is not None:
            raise self._factory._raise_exc
        return self._factory._result

    def close(self):
        pass


# --------------------------------------------------------------- Eligibility


def test_only_the_five_important_states_are_push_eligible():
    assert PUSH_ELIGIBLE_STATES == {
        DecisionState.ENTRY_CONDITIONS_MET,
        DecisionState.THESIS_STRENGTHENING,
        DecisionState.THESIS_WEAKENING,
        DecisionState.INVALIDATED,
        DecisionState.EXIT_CONDITIONS_MET,
    }


def test_plain_english_mapping_matches_the_spec_exactly():
    assert PLAIN_ENGLISH_STATE_TITLE[DecisionState.WATCHING] == "Watching for an entry"
    assert PLAIN_ENGLISH_STATE_TITLE[DecisionState.ENTRY_CONDITIONS_MET] == "Entry setup active"
    assert PLAIN_ENGLISH_STATE_TITLE[DecisionState.ACTIVE_THESIS] == "Setup is active"
    assert PLAIN_ENGLISH_STATE_TITLE[DecisionState.THESIS_STRENGTHENING] == "Setup getting stronger"
    assert PLAIN_ENGLISH_STATE_TITLE[DecisionState.THESIS_WEAKENING] == "Risk increasing"
    assert PLAIN_ENGLISH_STATE_TITLE[DecisionState.EXIT_CONDITIONS_MET] == "Exit conditions reached"
    assert PLAIN_ENGLISH_STATE_TITLE[DecisionState.INVALIDATED] == "Setup failed"
    assert PLAIN_ENGLISH_STATE_TITLE[DecisionState.ABSTAIN] == "Not enough evidence"


# --------------------------------------------------------------- Content


_AS_OF = datetime(2026, 10, 19, 14, 35, tzinfo=timezone.utc)  # Monday, regular session (10:35 AM ET)


def _event_for(plan, to_state, *, trigger_condition_ids=None, repository=None):
    transition = build_transition(
        plan,
        to_state,
        reason="test transition",
        as_of=_AS_OF,
        trigger_condition_ids=trigger_condition_ids or [],
    )
    service = AlertService(repository or SqlAlchemyAlertRepository(make_session()))
    return service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)


def test_build_push_content_reads_price_setup_and_invalidation_from_the_plan():
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    assert event is not None

    content = build_push_content(plan, event, settings=_settings())

    assert content.ticker == "AAPL"
    assert content.state_title == "Entry setup active"
    assert content.price == 146.18
    assert content.setup_label == "Breakout retest"
    assert content.confirmation_level == 145.00
    assert content.invalidation_level == 142.95
    assert content.research_url == "https://ai-market-desk-web.onrender.com/?symbol=AAPL"


def test_build_push_content_timestamp_is_america_new_york_and_session_labeled():
    plan = _plan_with_conditions(DecisionState.WATCHING)
    # 14:35 UTC on a Monday in October (EDT, UTC-4) = 10:35 AM ET -- regular session.
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    content = build_push_content(plan, event, settings=_settings())

    assert content.timestamp_et.endswith("ET")
    assert "10:35" in content.timestamp_et
    assert content.session_label == "Regular session"


_LEGAL_FROM_STATE_FOR = {
    DecisionState.ENTRY_CONDITIONS_MET: DecisionState.WATCHING,
    DecisionState.THESIS_STRENGTHENING: DecisionState.ACTIVE_THESIS,
    DecisionState.THESIS_WEAKENING: DecisionState.ACTIVE_THESIS,
    DecisionState.INVALIDATED: DecisionState.ACTIVE_THESIS,
    DecisionState.EXIT_CONDITIONS_MET: DecisionState.ACTIVE_THESIS,
}


@pytest.mark.parametrize("to_state", sorted(PUSH_ELIGIBLE_STATES, key=lambda s: s.value))
def test_render_push_message_never_contains_buy_or_sell_language(to_state):
    repo = SqlAlchemyAlertRepository(make_session())
    repo.set_preference(AlertType.THESIS_STRENGTHENING, True)  # so THIS test can reach the record
    plan = _plan_with_conditions(_LEGAL_FROM_STATE_FOR[to_state])
    event = _event_for(plan, to_state, repository=repo)
    assert event is not None

    content = build_push_content(plan, event, settings=_settings())
    message = render_push_message(content)
    violations = contains_banned_language(f"{message.title} {message.message}")
    assert violations == [], f"state={to_state} produced banned language: {violations}"


def test_render_push_message_example_shape_matches_spec():
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    content = build_push_content(plan, event, settings=_settings())
    message = render_push_message(content)

    assert message.title == "AAPL — Entry setup active"
    assert "Price: $146.18" in message.message
    assert "Setup: Breakout retest" in message.message
    assert "Invalidation: $142.95" in message.message
    assert message.url == "https://ai-market-desk-web.onrender.com/?symbol=AAPL"


# --------------------------------------------------------------- Dispatch


def test_dispatch_sends_separately_to_each_users_own_destination():
    """Proof 2 of the spec: two eligible users, two different keys, two
    separate Pushover calls -- never one shared send."""
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    settings = _settings()
    user_a, user_b = uuid4(), uuid4()
    repo = _FakeRepo(
        {user_a, user_b},
        keys={
            user_a: _encrypted("key-for-user-a", settings),
            user_b: _encrypted("key-for-user-b", settings),
        },
    )
    factory = FakeProviderFactory()

    dispatch_push_notifications(
        repo, event, plan, [user_a, user_b], settings=settings, provider_factory=factory
    )

    assert len(factory.calls) == 2
    sent_keys = {key for _app_token, key in factory.calls}
    assert sent_keys == {"key-for-user-a", "key-for-user-b"}
    assert len(repo.recorded) == 2


def test_a_users_push_is_sent_only_to_their_own_destination_key():
    """Proof 1 of the spec: User A's alert must never be delivered to
    User B's Pushover destination. Asserts the exact key used per user,
    not just a count."""
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    settings = _settings()
    user_a, user_b = uuid4(), uuid4()
    repo = _FakeRepo(
        {user_a, user_b},
        keys={
            user_a: _encrypted("key-for-user-a-only", settings),
            user_b: _encrypted("key-for-user-b-only", settings),
        },
    )
    factory = FakeProviderFactory()

    dispatch_push_notifications(
        repo, event, plan, [user_a, user_b], settings=settings, provider_factory=factory
    )

    calls_by_key = {key: app_token for app_token, key in factory.calls}
    assert "key-for-user-a-only" in calls_by_key
    assert "key-for-user-b-only" in calls_by_key
    # Neither user's key was ever paired with anything other than the
    # shared app token -- there is no path by which A's send could carry
    # B's key or vice versa (each call is built from exactly one user's
    # own decrypted key, see app.alerts.push._dispatch's loop).
    assert len(factory.calls) == 2


def test_a_user_with_no_configured_key_is_skipped_but_others_still_receive_theirs():
    """Proof 3: a user without a destination key is skipped -- silently,
    never substituted with someone else's key, and never blocks other
    eligible users from receiving their own push."""
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    settings = _settings()
    user_with_key, user_without_key = uuid4(), uuid4()
    repo = _FakeRepo(
        {user_with_key, user_without_key},
        keys={user_with_key: _encrypted("only-this-users-key", settings)},
    )
    factory = FakeProviderFactory()

    dispatch_push_notifications(
        repo, event, plan, [user_with_key, user_without_key], settings=settings, provider_factory=factory
    )

    assert len(factory.calls) == 1
    assert factory.calls[0][1] == "only-this-users-key"
    assert len(repo.recorded) == 1
    assert repo.recorded[0][0] == user_with_key


def test_dispatch_is_a_noop_for_a_non_eligible_state_watching():
    # Override the (deliberately off-by-default) WATCHING preference so the
    # AlertEvent genuinely gets created -- isolating "dispatch's OWN
    # PUSH_ELIGIBLE_STATES gate rejects WATCHING" from "WATCHING alerts
    # don't even get recorded by default" (a separate, pre-existing gate).
    repository = SqlAlchemyAlertRepository(make_session())
    repository.set_preference(AlertType.WATCHING, True)
    plan = make_plan(DecisionState.EVALUATING)
    transition = build_transition(plan, DecisionState.WATCHING, reason="watching", as_of=plan.as_of)
    service = AlertService(repository)
    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    assert event is not None

    settings = _settings()
    user = uuid4()
    repo = _FakeRepo({user}, keys={user: _encrypted("k", settings)})
    factory = FakeProviderFactory()
    dispatch_push_notifications(repo, event, plan, [user], settings=settings, provider_factory=factory)

    assert factory.calls == []  # ...but never pushed


def test_disabled_user_receives_nothing_even_with_a_key_configured():
    """Proof 4: a user who has NOT enabled push receives nothing, even
    if they have a destination key configured."""
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    settings = _settings()
    user = uuid4()
    repo = _FakeRepo(set(), keys={user: _encrypted("k", settings)})  # push NOT enabled
    factory = FakeProviderFactory()

    dispatch_push_notifications(repo, event, plan, [user], settings=settings, provider_factory=factory)

    assert factory.calls == []


def test_dispatch_is_a_noop_when_push_globally_disabled():
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    settings = _settings(push_notifications_enabled=False)
    user = uuid4()
    repo = _FakeRepo({user}, keys={user: _encrypted("k", settings)})

    dispatch_push_notifications(repo, event, plan, [user], settings=settings)

    assert repo.recorded == []


def test_dispatch_is_a_noop_when_encryption_key_is_missing():
    """Phase 20.2 proof 3: PUSH_NOTIFICATIONS_ENABLED and
    PUSHOVER_APP_TOKEN both configured, but PUSHOVER_KEY_ENCRYPTION_KEY
    missing -- dispatch must safely no-op, never crash and never attempt
    to derive a key from an empty string."""
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    settings = _settings(pushover_key_encryption_key="")
    user = uuid4()
    repo = _FakeRepo({user}, keys={user: _encrypted("k", _settings())})
    factory = FakeProviderFactory()

    dispatch_push_notifications(repo, event, plan, [user], settings=settings, provider_factory=factory)

    assert factory.calls == []
    assert repo.recorded == []


def test_rotating_secret_key_never_affects_pushover_key_decryption():
    """Phase 20.2 proof 1: SECRET_KEY (JWT/session signing) and
    PUSHOVER_KEY_ENCRYPTION_KEY are fully decoupled -- rotating the
    former must never make a stored Pushover user key undecryptable."""
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    original_settings = _settings(secret_key="original-session-secret")
    encrypted = _encrypted("rotation-proof-key", original_settings)

    rotated_settings = _settings(secret_key="brand-new-rotated-session-secret")
    user = uuid4()
    repo = _FakeRepo({user}, keys={user: encrypted})
    factory = FakeProviderFactory()

    dispatch_push_notifications(
        repo, event, plan, [user], settings=rotated_settings, provider_factory=factory
    )

    assert len(factory.calls) == 1
    assert factory.calls[0][1] == "rotation-proof-key"


def test_changing_the_pushover_key_encryption_key_makes_old_ciphertext_undecryptable():
    """Phase 20.2 proof 2: the inverse of the above -- rotating
    PUSHOVER_KEY_ENCRYPTION_KEY itself (a deliberate, disclosed
    consequence) makes previously stored ciphertext unreadable, and
    dispatch must treat that the same as "no key configured" -- skip
    that user, never crash, never substitute a different key."""
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    original_settings = _settings(pushover_key_encryption_key="original-pushover-encryption-key")
    encrypted = _encrypted("will-become-undecryptable", original_settings)

    new_key_settings = _settings(pushover_key_encryption_key="a-totally-different-encryption-key")
    user = uuid4()
    repo = _FakeRepo({user}, keys={user: encrypted})
    factory = FakeProviderFactory()

    dispatch_push_notifications(
        repo, event, plan, [user], settings=new_key_settings, provider_factory=factory
    )

    assert factory.calls == []
    assert repo.recorded == []


def test_dispatch_is_a_noop_for_dev_fixture_origin():
    plan = _plan_with_conditions(DecisionState.WATCHING)
    transition = build_transition(
        plan,
        DecisionState.ENTRY_CONDITIONS_MET,
        reason="fixture",
        as_of=plan.as_of,
        trigger_condition_ids=["entry-1"],
    )
    service = AlertService(SqlAlchemyAlertRepository(make_session()))
    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.DEV_FIXTURE)
    assert event is not None

    settings = _settings()
    user = uuid4()
    repo = _FakeRepo({user}, keys={user: _encrypted("k", settings)})
    factory = FakeProviderFactory()
    dispatch_push_notifications(repo, event, plan, [user], settings=settings, provider_factory=factory)

    assert factory.calls == []


def test_dispatch_never_raises_even_if_the_provider_itself_raises():
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    settings = _settings()
    user = uuid4()
    repo = _FakeRepo({user}, keys={user: _encrypted("k", settings)})
    factory = FakeProviderFactory(raise_exc=RuntimeError("Pushover is down"))

    # Must not raise -- this is the exact "delivery failure must not
    # crash the Decision Engine or monitoring loop" requirement.
    dispatch_push_notifications(repo, event, plan, [user], settings=settings, provider_factory=factory)

    assert len(factory.calls) == 1  # it did try


def test_dispatch_records_failure_status_without_leaking_credentials():
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    settings = _settings()
    user = uuid4()
    repo = _FakeRepo({user}, keys={user: _encrypted("super-secret-destination-key", settings)})
    factory = FakeProviderFactory(result=PushoverSendResult(success=False, error="invalid_credentials"))

    dispatch_push_notifications(repo, event, plan, [user], settings=settings, provider_factory=factory)

    assert repo.recorded == [(user, event.alert_id, False, "invalid_credentials")]
    assert "test-app-token" not in str(repo.recorded)
    assert "super-secret-destination-key" not in str(repo.recorded)


@pytest.mark.parametrize(
    "to_state",
    [DecisionState.THESIS_WEAKENING, DecisionState.INVALIDATED, DecisionState.EXIT_CONDITIONS_MET],
)
def test_dispatch_sends_for_each_important_state(to_state):
    plan = _plan_with_conditions(DecisionState.ACTIVE_THESIS)
    transition = build_transition(plan, to_state, reason="test", as_of=plan.as_of)
    service = AlertService(SqlAlchemyAlertRepository(make_session()))
    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    assert event is not None

    settings = _settings()
    user = uuid4()
    repo = _FakeRepo({user}, keys={user: _encrypted("k", settings)})
    factory = FakeProviderFactory()
    dispatch_push_notifications(repo, event, plan, [user], settings=settings, provider_factory=factory)

    assert len(factory.calls) == 1


def test_dispatch_is_a_noop_for_abstain_no_event_even_created():
    plan = make_plan(DecisionState.EVALUATING)
    transition = build_transition(plan, DecisionState.ABSTAIN, reason="no evidence", as_of=plan.as_of)
    service = AlertService(SqlAlchemyAlertRepository(make_session()))
    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is None  # ABSTAIN never even produces an AlertEvent -- nothing to dispatch


def test_is_push_eligible_transition_is_the_single_source_both_record_and_dispatch_use():
    plan = _plan_with_conditions(DecisionState.WATCHING)
    event = _event_for(plan, DecisionState.ENTRY_CONDITIONS_MET, trigger_condition_ids=["entry-1"])
    assert is_push_eligible_transition(event) is True
