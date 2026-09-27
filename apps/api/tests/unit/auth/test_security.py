"""Phase 16 (§12/§14): password hashing and JWT session token behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.auth.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.config import Settings

_SETTINGS = Settings(
    _env_file=None, secret_key="test-secret-that-is-long-enough-32b", access_token_ttl_minutes=60
)


def test_hash_password_never_stores_plaintext():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_verify_password_handles_malformed_hash_without_crashing():
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_access_token_round_trips_user_id():
    user_id = uuid4()
    token = create_access_token(user_id, settings=_SETTINGS)
    assert decode_access_token(token, settings=_SETTINGS) == user_id


def test_expired_token_is_rejected():
    user_id = uuid4()
    issued_at = datetime.now(timezone.utc) - timedelta(hours=2)
    token = create_access_token(user_id, settings=_SETTINGS, now=issued_at)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, settings=_SETTINGS)


def test_token_signed_with_a_different_secret_is_rejected():
    user_id = uuid4()
    token = create_access_token(user_id, settings=_SETTINGS)
    other_settings = Settings(_env_file=None, secret_key="a-different-secret-thats-also-long-32b")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, settings=other_settings)


def test_garbage_token_is_rejected():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.jwt", settings=_SETTINGS)
