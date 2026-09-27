"""Phase 16/16.1: password hashing and JWT session tokens -- the ONLY place
either happens in this codebase. Uses mature, standard libraries (bcrypt
for hashing, PyJWT for signing) rather than inventing cryptography.

Phase 16.1: the JWT is no longer purely stateless. Every token now carries
a `jti` (JWT ID) claim naming a row in `user_sessions`
(app.auth.sessions.SqlAlchemyUserSessionRepository) -- a token only
authenticates a request while that row still exists, is unexpired, and is
unrevoked. This is what makes logout, forced expiration, and disabling a
user actually take effect immediately, instead of only once the token's
own `exp` claim (still enforced as a hard upper bound) arrives. See
docs/decisions/0020.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class TokenPayload:
    user_id: UUID
    jti: str


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
) -> IssuedToken:
    settings = settings or get_settings()
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=settings.access_token_ttl_minutes)
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "type": _TOKEN_TYPE,
        "jti": jti,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return IssuedToken(token=token, jti=jti, issued_at=issued_at, expires_at=expires_at)


def decode_access_token(token: str, *, settings: Optional[Settings] = None) -> TokenPayload:
    """Returns the token's claimed user id and session id (jti), or raises
    InvalidTokenError. Signature/expiry verification only -- this function
    alone can NEVER tell you whether the session has been logged out or the
    user disabled; callers must also check session validity (see
    app.auth.dependencies.get_current_user)."""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Malformed, expired, or unsigned token") from exc

    if payload.get("type") != _TOKEN_TYPE:
        raise InvalidTokenError("Wrong token type")

    subject = payload.get("sub")
    jti = payload.get("jti")
    if not subject or not jti:
        raise InvalidTokenError("Missing subject or session claim")

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError("Subject claim is not a valid user id") from exc

    return TokenPayload(user_id=user_id, jti=jti)
