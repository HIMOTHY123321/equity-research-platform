"""Phase 16/16.1: the FastAPI dependencies every user-scoped route depends
on. `get_current_user` is Authorization -- "who is this request allowed to
act as?" -- never trusting a client-supplied user id/header for identity,
only a validated, server-signed session token whose `jti` still names a
live, unexpired, unrevoked row in `user_sessions` (app.auth.sessions).

Phase 16.1: the HttpOnly session cookie (app.auth.cookies) is the primary
transport -- the frontend never reads or stores the token itself. The
`Authorization: Bearer` header is kept only as a fallback for non-browser
callers (tests, scripts, curl) that cannot rely on cookie jars; an explicit
header always wins over an ambient cookie when both are present (the
browser frontend never sends a header at all, so this never affects it).
"""

from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.cookies import SESSION_COOKIE_NAME
from app.auth.repository import SqlAlchemyUserRepository, UserRepository
from app.auth.security import InvalidTokenError, TokenPayload, decode_access_token
from app.auth.sessions import SessionRepository, SqlAlchemyUserSessionRepository
from app.database.models import User
from app.database.session import get_db

_bearer_scheme = HTTPBearer(auto_error=False)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return SqlAlchemyUserRepository(db)


def get_session_repository(db: Session = Depends(get_db)) -> SessionRepository:
    return SqlAlchemyUserSessionRepository(db)


def _extract_token(
    session_cookie: Optional[str], credentials: Optional[HTTPAuthorizationCredentials]
) -> Optional[str]:
    # An explicitly-presented Authorization header always wins over an
    # ambient cookie -- callers that go out of their way to name a session
    # (tests, scripts, a tool that happens to also be carrying a stale
    # cookie from a different login) mean exactly that token, not whatever
    # the cookie jar last picked up. The browser frontend never sends an
    # Authorization header at all, so this never affects it.
    if credentials:
        return credentials.credentials
    if session_cookie:
        return session_cookie
    return None


def _decode_and_verify(token: str, session_repository: SessionRepository) -> TokenPayload:
    try:
        payload = decode_access_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from exc
    if not session_repository.is_valid(payload.jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")
    return payload


def get_current_user(
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    user_repository: UserRepository = Depends(get_user_repository),
    session_repository: SessionRepository = Depends(get_session_repository),
) -> User:
    token = _extract_token(session_cookie, credentials)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = _decode_and_verify(token, session_repository)
    user = user_repository.get_by_id(payload.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return user


def get_current_user_optional(
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    user_repository: UserRepository = Depends(get_user_repository),
    session_repository: SessionRepository = Depends(get_session_repository),
) -> Optional[User]:
    """For endpoints that behave differently for signed-in vs anonymous
    callers but never require a session -- never used to bypass ownership
    checks; those must always use `get_current_user`."""
    token = _extract_token(session_cookie, credentials)
    if token is None:
        return None
    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        return None
    if not session_repository.is_valid(payload.jti):
        return None
    user = user_repository.get_by_id(payload.user_id)
    if user is None or user.status != "active":
        return None
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Phase 16 (§53/§107): admin authorization is ALWAYS re-derived from
    the authenticated user's own server-side `role` column -- never from a
    client-supplied header/field claiming admin status."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
