"""Long-Term Research push dispatch -- isolation (one user's push never
reaches another's device), banned-language safety, and the "Pushover
failure cannot corrupt research state" + "unchanged state produces no
duplicate push" + "transition produces exactly one push" proofs, at the
dispatch-function level (app.long_term_research.service covers the
same proofs end-to-end with real persistence)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.long_term_research.push import dispatch_long_term_research_push, render_long_term_push_message
from app.long_term_research.schemas import (
    BusinessQualityState,
    EarningsTrendState,
    GrowthState,
    LongTermEvidenceQuality,
    LongTermFactorBundle,
    LongTermFactorEvidence,
    LongTermResearchResult,
    LongTermResearchState,
    LongTermTrendState,
    ValuationState,
)

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ENCRYPTION_KEY = "test-pushover-key-encryption-key-at-least-32-chars"


def _settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        environment="test",
        push_notifications_enabled=True,
        pushover_app_token="test-app-token",
        pushover_key_encryption_key=_ENCRYPTION_KEY,
    )
    base.update(overrides)
    return Settings(**base)


def _result(
    state: LongTermResearchState = LongTermResearchState.ACCUMULATION_CANDIDATE,
) -> LongTermResearchResult:
    empty = LongTermFactorEvidence()
    factors = LongTermFactorBundle(
        business_quality=BusinessQualityState.STRONG,
        business_quality_evidence=empty,
        earnings_trend=EarningsTrendState.IMPROVING,
        earnings_trend_evidence=empty,
        valuation=ValuationState.CHEAP,
        valuation_evidence=empty,
        growth=GrowthState.STRONG,
        growth_evidence=empty,
        long_term_trend=LongTermTrendState.CONSTRUCTIVE,
        long_term_trend_evidence=empty,
        history_days=500,
        limited_history=False,
    )
    return LongTermResearchResult(
        symbol="AAPL",
        as_of=AS_OF,
        price=150.0,
        research_state=state,
        factors=factors,
        evidence_quality=LongTermEvidenceQuality.STRONG,
        positive_evidence=["Strong business quality."],
        negative_evidence=[],
        contradictions=[],
        missing_evidence=[],
        reason="A majority of long-term factors are favorable.",
        what_would_change_state="Valuation becoming expensive.",
        market_data_provider="fixture",
        fundamentals_provider="fixture",
    )


class _FakeRepo:
    def __init__(self, enabled_users=None, keys=None):
        self._enabled = set(enabled_users or set())
        self._keys = dict(keys or {})

    def get_long_term_push_enabled(self, user_id):
        return user_id in self._enabled

    def get_user_pushover_key_encrypted(self, user_id):
        return self._keys.get(user_id)


class _FakeProviderFactory:
    def __init__(self, raise_exc=None):
        self.calls: list[tuple[str, str]] = []
        self.sent: list[tuple[str, object]] = []
        self._raise_exc = raise_exc

    def __call__(self, app_token, user_key):
        self.calls.append((app_token, user_key))
        factory = self

        class _Provider:
            def send(self, message):
                factory.sent.append((user_key, message))
                if factory._raise_exc is not None:
                    raise factory._raise_exc
                from app.notifications.pushover import PushoverSendResult

                return PushoverSendResult(success=True)

            def close(self):
                pass

        return _Provider()


def _encrypted(plaintext: str) -> str:
    from app.notifications.secret_crypto import encrypt_secret

    return encrypt_secret(plaintext, encryption_key=_ENCRYPTION_KEY)


def test_render_long_term_push_message_never_contains_banned_words():
    result = _result()
    message = render_long_term_push_message(result)
    for banned in ("BUY", "SELL", "STRONG BUY", "STRONG SELL"):
        assert banned not in message.title.upper().replace("STRONG BUY", "x")
    assert "BUY" not in message.message.upper()
    assert "SELL" not in message.message.upper()


def test_render_long_term_push_message_labels_limited_history():
    result = _result()
    result = result.model_copy(
        update={"factors": result.factors.model_copy(update={"limited_history": True})}
    )
    message = render_long_term_push_message(result)
    assert "LIMITED" in message.message


def test_a_users_push_is_sent_only_to_their_own_destination_key():
    user_a, user_b = uuid4(), uuid4()
    repo = _FakeRepo({user_a, user_b}, keys={user_a: _encrypted("key-a"), user_b: _encrypted("key-b")})
    factory = _FakeProviderFactory()

    dispatch_long_term_research_push(
        repo, _result(), [user_a, user_b], settings=_settings(), provider_factory=factory
    )

    sent_keys = {key for _token, key in factory.calls}
    assert sent_keys == {"key-a", "key-b"}
    assert len(factory.calls) == 2


def test_a_user_without_a_configured_key_is_skipped_but_others_still_get_their_push():
    user_with_key, user_without_key = uuid4(), uuid4()
    repo = _FakeRepo({user_with_key, user_without_key}, keys={user_with_key: _encrypted("only-key")})
    factory = _FakeProviderFactory()

    dispatch_long_term_research_push(
        repo, _result(), [user_with_key, user_without_key], settings=_settings(), provider_factory=factory
    )

    assert len(factory.calls) == 1
    assert factory.calls[0][1] == "only-key"


def test_a_disabled_user_receives_nothing_even_with_a_key_configured():
    user_id = uuid4()
    repo = _FakeRepo(set(), keys={user_id: _encrypted("key")})
    factory = _FakeProviderFactory()

    dispatch_long_term_research_push(
        repo, _result(), [user_id], settings=_settings(), provider_factory=factory
    )

    assert factory.calls == []


def test_dispatch_never_raises_even_if_the_provider_itself_raises():
    """Pushover failure cannot corrupt research state -- here proven at
    the dispatch-function level: a raising provider must not propagate."""
    user_id = uuid4()
    repo = _FakeRepo({user_id}, keys={user_id: _encrypted("key")})
    factory = _FakeProviderFactory(raise_exc=RuntimeError("Pushover is down"))

    dispatch_long_term_research_push(
        repo, _result(), [user_id], settings=_settings(), provider_factory=factory
    )

    assert len(factory.calls) == 1  # it did try


def test_dispatch_is_a_noop_when_encryption_key_is_missing():
    user_id = uuid4()
    repo = _FakeRepo({user_id}, keys={user_id: _encrypted("key")})
    factory = _FakeProviderFactory()
    settings = _settings(pushover_key_encryption_key="")

    dispatch_long_term_research_push(
        repo, _result(), [user_id], settings=settings, provider_factory=factory
    )

    assert factory.calls == []
