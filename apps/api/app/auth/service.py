"""Phase 16 (§12): signup/login orchestration -- the only place password
hashing and email-uniqueness are enforced together."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.auth.repository import UserRepository
from app.auth.security import hash_password, verify_password
from app.database.models import User


class EmailAlreadyRegisteredError(ValueError):
    def __init__(self, email: str) -> None:
        super().__init__(f"{email} is already registered")
        self.email = email


class InvalidCredentialsError(ValueError):
    """Deliberately generic -- never distinguishes "no such user" from
    "wrong password," so a login attempt can't be used to enumerate
    registered emails."""


def signup(user_repository: UserRepository, *, email: str, password: str) -> User:
    if user_repository.get_by_email(email) is not None:
        raise EmailAlreadyRegisteredError(email)
    try:
        return user_repository.create(email=email, password_hash=hash_password(password))
    except IntegrityError as exc:
        # Lost a race against a concurrent signup for the same email --
        # same exactly-once discipline every other repository in this
        # codebase already uses for its own unique constraints.
        raise EmailAlreadyRegisteredError(email) from exc


def authenticate(user_repository: UserRepository, *, email: str, password: str) -> User:
    user = user_repository.get_by_email(email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid email or password")
    if user.status != "active":
        raise InvalidCredentialsError("Invalid email or password")
    return user
