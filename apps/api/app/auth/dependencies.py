"""Phase 16 (§13): the one FastAPI dependency every user-scoped route must
depend on. `get_current_user` is Authorization -- "who is this request
allowed to act as?" -- never trusting a client-supplied user id/header for
identity, only a validated, server-signed session token.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.repository import SqlAlchemyUserRepository, UserRepository
from app.auth.security import InvalidTokenError, decode_access_token
from app.database.models import User
from app.database.session import get_db

_bearer_scheme = HTTPBearer(auto_error=False)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return SqlAlchemyUserRepository(db)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    user_repository: UserRepository = Depends(get_user_repository),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from exc

    user = user_repository.get_by_id(user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    user_repository: UserRepository = Depends(get_user_repository),
) -> Optional[User]:
    """For endpoints that behave differently for signed-in vs anonymous
    callers but never require a session -- never used to bypass ownership
    checks; those must always use `get_current_user`."""
    if credentials is None:
        return None
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        return None
    user = user_repository.get_by_id(user_id)
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
