"""Phase 19.6: unit coverage for app.auth.ws_ticket in isolation -- no DB,
no WebSocket handshake, no HTTP layer. Integration-level coverage (the real
`/api/live/ws-ticket` endpoint and the `/api/live/stream` handshake itself)
lives in tests/integration/test_live_ws_ticket.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.auth.security import InvalidTokenError, create_access_token
from app.auth.ws_ticket import (
    WS_TICKET_TTL_SECONDS,
    consume_ws_ticket_once,
    create_ws_ticket,
    decode_ws_ticket,
)
from app.config import Settings


def _settings() -> Settings:
    return Settings(_env_file=None, secret_key="test-secret-key-at-least-32-chars-long", environment="test")


def test_a_freshly_issued_ticket_decodes_to_the_same_user_and_session():
    user_id = uuid.uuid4()
    settings = _settings()
    issued = create_ws_ticket(user_id, "session-jti-1", settings=settings)

    payload = decode_ws_ticket(issued.token, settings=settings)

    assert payload.user_id == user_id
    assert payload.session_jti == "session-jti-1"
    # JWT "exp" is whole-second epoch precision, so the round-tripped
    # value loses sub-second precision -- compare at that same precision.
    assert int(payload.expires_at.timestamp()) == int(issued.expires_at.timestamp())


def test_ticket_lifetime_matches_the_documented_constant():
    issued = create_ws_ticket(uuid.uuid4(), "session-jti", settings=_settings())
    assert 0 < WS_TICKET_TTL_SECONDS <= 60
    lifetime = (issued.expires_at - datetime.now(timezone.utc)).total_seconds()
    assert WS_TICKET_TTL_SECONDS - 2 <= lifetime <= WS_TICKET_TTL_SECONDS


def test_an_expired_ticket_is_rejected():
    settings = _settings()
    issued_at = datetime.now(timezone.utc) - timedelta(hours=1)
    issued = create_ws_ticket(uuid.uuid4(), "session-jti", settings=settings, now=issued_at)

    with pytest.raises(InvalidTokenError):
        decode_ws_ticket(issued.token, settings=settings)


def test_a_malformed_ticket_is_rejected():
    with pytest.raises(InvalidTokenError):
        decode_ws_ticket("not-a-real-jwt-at-all", settings=_settings())


def test_a_ticket_signed_with_the_wrong_secret_is_rejected():
    settings = _settings()
    issued = create_ws_ticket(uuid.uuid4(), "session-jti", settings=settings)
    wrong_settings = Settings(
        _env_file=None, secret_key="a-totally-different-secret-value", environment="test"
    )

    with pytest.raises(InvalidTokenError):
        decode_ws_ticket(issued.token, settings=wrong_settings)


def test_a_real_session_access_token_is_rejected_as_a_ws_ticket():
    """Wrong-purpose rejection: a genuine, validly-signed session JWT
    (type="access") must never be accepted where a ws-ticket
    (type="ws_stream_ticket") is expected, even though both are signed
    with the same secret."""
    settings = _settings()
    issued = create_access_token(uuid.uuid4(), settings=settings)

    with pytest.raises(InvalidTokenError):
        decode_ws_ticket(issued.token, settings=settings)


def test_a_ws_ticket_is_rejected_by_the_session_token_decoder_too():
    """The inverse of the above -- a ws-ticket must never authenticate as
    a normal session token either."""
    from app.auth.security import decode_access_token

    settings = _settings()
    issued = create_ws_ticket(uuid.uuid4(), "session-jti", settings=settings)

    with pytest.raises(InvalidTokenError):
        decode_access_token(issued.token, settings=settings)


def test_a_ticket_missing_required_claims_is_rejected():
    settings = _settings()
    payload = {
        "sub": str(uuid.uuid4()),
        "type": "ws_stream_ticket",
        # Missing "session" and "jti" claims entirely.
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(seconds=30)).timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

    with pytest.raises(InvalidTokenError):
        decode_ws_ticket(token, settings=settings)


def test_consuming_a_ticket_twice_the_second_attempt_is_rejected():
    ticket_jti = uuid.uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=WS_TICKET_TTL_SECONDS)

    assert consume_ws_ticket_once(ticket_jti, expires_at) is True
    assert consume_ws_ticket_once(ticket_jti, expires_at) is False


def test_different_tickets_can_each_be_consumed_once():
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=WS_TICKET_TTL_SECONDS)
    jti_a, jti_b = uuid.uuid4().hex, uuid.uuid4().hex

    assert consume_ws_ticket_once(jti_a, expires_at) is True
    assert consume_ws_ticket_once(jti_b, expires_at) is True
    assert consume_ws_ticket_once(jti_a, expires_at) is False
    assert consume_ws_ticket_once(jti_b, expires_at) is False


def test_an_expired_entry_is_swept_and_its_jti_can_be_reused_by_a_new_ticket():
    """Not a security concern -- a ticket's SIGNATURE has already expired
    (rejected by decode_ws_ticket well before consume_ws_ticket_once is
    ever called on it) long before the replay guard would consider
    sweeping it; this only proves the in-memory guard doesn't grow
    unbounded forever."""
    ticket_jti = uuid.uuid4().hex
    already_expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert consume_ws_ticket_once(ticket_jti, already_expired) is True

    later = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert consume_ws_ticket_once(ticket_jti, later, now=later) is True
