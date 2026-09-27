"""Phase 16 (§12/§14): password hashing and JWT session tokens -- the ONLY
place either happens in this codebase. Uses mature, standard libraries
(bcrypt for hashing, PyJWT for signing) rather than inventing cryptography.

JWT is intentionally stateless: a token is valid until it expires
(`access_token_ttl_minutes`, default 24h) or the signing key changes.
There is no server-side revocation list in this phase -- "logout" is a
client-side token discard. This is an explicit, disclosed limitation (see
the Phase 16 final report), not an oversight; a revocation/refresh-token
architecture is deferred.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import bcrypt
import jwt

from app.config import Settings, get_settings

_TOKEN_TYPE = "access"


class InvalidTokenError(ValueError):
    """Raised for any malformed, expired, wrong-type, or bad-signature
    token -- callers never need to distinguish the reason (that would leak
    information to a caller probing tokens); it is always just "not a
    valid session"."""


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed stored hash -- never crash the login attempt, just
        # treat it as a failed verification.
        return False


def create_access_token(
    user_id: UUID, *, settings: Optional[Settings] = None, now: Optional[datetime] = None
) -> str:
    settings = settings or get_settings()
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "type": _TOKEN_TYPE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, *, settings: Optional[Settings] = None) -> UUID:
    """Returns the authenticated user's id, or raises InvalidTokenError."""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Malformed, expired, or unsigned token") from exc

    if payload.get("type") != _TOKEN_TYPE:
        raise InvalidTokenError("Wrong token type")

    subject = payload.get("sub")
    if not subject:
        raise InvalidTokenError("Missing subject claim")

    try:
        return UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError("Subject claim is not a valid user id") from exc
