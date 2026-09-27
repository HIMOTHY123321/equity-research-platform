"""Phase 16: persistence for the `users` table. Same ABC + SqlAlchemy-
implementation pattern every other repository in this codebase follows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Base, User


class UserRepository(ABC):
    @abstractmethod
    def get_by_id(self, user_id: UUID) -> Optional[User]: ...

    @abstractmethod
    def get_by_email(self, email: str) -> Optional[User]: ...

    @abstractmethod
    def create(self, *, email: str, password_hash: str) -> User: ...

    @abstractmethod
    def update_plan(self, user: User, plan: str) -> User: ...


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        Base.metadata.create_all(bind=session.get_bind(), tables=[User.__table__], checkfirst=True)

    def get_by_id(self, user_id: UUID) -> Optional[User]:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> Optional[User]:
        normalized = email.strip().lower()
        return self._session.execute(
            select(User).where(User.email == normalized)
        ).scalar_one_or_none()

    def create(self, *, email: str, password_hash: str) -> User:
        user = User(email=email.strip().lower(), password_hash=password_hash)
        self._session.add(user)
        self._session.commit()
        self._session.refresh(user)
        return user

    def update_plan(self, user: User, plan: str) -> User:
        user.plan = plan
        self._session.commit()
        self._session.refresh(user)
        return user
