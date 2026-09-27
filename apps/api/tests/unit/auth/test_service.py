"""Phase 16 (§12): signup/login orchestration -- email uniqueness and
generic (non-enumerating) invalid-credentials behavior."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.repository import SqlAlchemyUserRepository
from app.auth.service import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    authenticate,
    signup,
)


def _repo():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    session = sessionmaker(bind=engine)()
    return SqlAlchemyUserRepository(session)


def test_signup_creates_a_user_with_a_hashed_password():
    repo = _repo()
    user = signup(repo, email="Trader@Example.com", password="hunter2hunter2")
    assert user.email == "trader@example.com"  # normalized lowercase
    assert user.password_hash != "hunter2hunter2"


def test_signup_rejects_duplicate_email():
    repo = _repo()
    signup(repo, email="trader@example.com", password="hunter2hunter2")
    with pytest.raises(EmailAlreadyRegisteredError):
        signup(repo, email="trader@example.com", password="differentpassword")


def test_authenticate_succeeds_with_correct_credentials():
    repo = _repo()
    signup(repo, email="trader@example.com", password="hunter2hunter2")
    user = authenticate(repo, email="trader@example.com", password="hunter2hunter2")
    assert user.email == "trader@example.com"


def test_authenticate_rejects_wrong_password():
    repo = _repo()
    signup(repo, email="trader@example.com", password="hunter2hunter2")
    with pytest.raises(InvalidCredentialsError):
        authenticate(repo, email="trader@example.com", password="wrongpassword")


def test_authenticate_rejects_unknown_email_with_the_same_generic_error():
    repo = _repo()
    # Same exception type/message as a wrong-password attempt -- never lets
    # a caller distinguish "no such account" from "wrong password."
    with pytest.raises(InvalidCredentialsError):
        authenticate(repo, email="nobody@example.com", password="whatever12345")


def test_authenticate_rejects_disabled_account():
    repo = _repo()
    user = signup(repo, email="trader@example.com", password="hunter2hunter2")
    user.status = "disabled"
    repo._session.commit()  # test-only direct mutation to simulate an admin disabling the account
    with pytest.raises(InvalidCredentialsError):
        authenticate(repo, email="trader@example.com", password="hunter2hunter2")
