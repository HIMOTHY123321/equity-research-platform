"""Phase 16.1: server-verifiable session storage -- the thing that makes a
JWT's validity actually revocable before its own `exp` claim arrives.
`jti` (never the token string itself) is what's stored, matching the
`jti` claim app.auth.security embeds in every issued token."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Base, UserSessionRecord


class SessionRepository(ABC):
    @abstractmethod
    def create(self, *, user_id: UUID, jti: str, expires_at: datetime) -> None: ...

    @abstractmethod
    def is_valid(self, jti: str, *, now: Optional[datetime] = None) -> bool:
        """True only if a session row exists for `jti`, has not been
        revoked, and has not passed its own `expires_at` -- all three are
        required, not just signature validity on the token itself."""
        ...

    @abstractmethod
    def revoke(self, jti: str) -> None: ...

    @abstractmethod
    def revoke_all_for_user(self, user_id: UUID) -> int:
        """Revokes every active session for a user -- used when disabling
        an account, so existing sessions cannot outlive the decision to
        disable it."""
        ...


class SqlAlchemyUserSessionRepository(SessionRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        Base.metadata.create_all(
            bind=session.get_bind(), tables=[UserSessionRecord.__table__], checkfirst=True
        )

    def create(self, *, user_id: UUID, jti: str, expires_at: datetime) -> None:
        self._session.add(UserSessionRecord(user_id=user_id, jti=jti, expires_at=expires_at))
        self._session.commit()

    def _get(self, jti: str) -> Optional[UserSessionRecord]:
        return self._session.execute(
            select(UserSessionRecord).where(UserSessionRecord.jti == jti)
        ).scalar_one_or_none()

    def is_valid(self, jti: str, *, now: Optional[datetime] = None) -> bool:
        row = self._get(jti)
        if row is None or row.revoked_at is not None:
            return False
        now = now or datetime.now(timezone.utc)
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > now

    def revoke(self, jti: str) -> None:
        row = self._get(jti)
        if row is None or row.revoked_at is not None:
            return
        row.revoked_at = datetime.now(timezone.utc)
        self._session.commit()

    def revoke_all_for_user(self, user_id: UUID) -> int:
        rows = self._session.execute(
            select(UserSessionRecord).where(
                UserSessionRecord.user_id == user_id, UserSessionRecord.revoked_at.is_(None)
            )
        ).scalars()
        now = datetime.now(timezone.utc)
        count = 0
        for row in rows:
            row.revoked_at = now
            count += 1
        if count:
            self._session.commit()
        return count
