"""Phase 16 (§18/§19): the auth rate limiter is a plain FastAPI dependency
(not slowapi's route decorator, which was found to break FastAPI's body-
parameter signature detection). Disabled outside production by design --
see app.rate_limiting's own module docstring for why."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

import app.rate_limiting as rate_limiting


def _fake_request(ip: str = "203.0.113.5"):
    request = Mock()
    request.client.host = ip
    return request


def test_rate_limit_is_a_no_op_when_disabled():
    assert rate_limiting._ENABLED is False  # development/test default
    for _ in range(1000):
        rate_limiting.auth_rate_limit(_fake_request())  # never raises


def test_rate_limit_blocks_after_the_configured_threshold_when_enabled(monkeypatch):
    monkeypatch.setattr(rate_limiting, "_ENABLED", True)
    # Fresh storage/strategy so this test doesn't inherit hits from any
    # other test that happens to run in the same process.
    from limits.storage import MemoryStorage
    from limits.strategies import FixedWindowRateLimiter

    monkeypatch.setattr(rate_limiting, "_storage", MemoryStorage())
    monkeypatch.setattr(rate_limiting, "_strategy", FixedWindowRateLimiter(rate_limiting._storage))

    request = _fake_request("198.51.100.9")
    for _ in range(20):
        rate_limiting.auth_rate_limit(request)

    with pytest.raises(HTTPException) as excinfo:
        rate_limiting.auth_rate_limit(request)
    assert excinfo.value.status_code == 429


def test_rate_limit_is_scoped_per_ip(monkeypatch):
    monkeypatch.setattr(rate_limiting, "_ENABLED", True)
    from limits.storage import MemoryStorage
    from limits.strategies import FixedWindowRateLimiter

    monkeypatch.setattr(rate_limiting, "_storage", MemoryStorage())
    monkeypatch.setattr(rate_limiting, "_strategy", FixedWindowRateLimiter(rate_limiting._storage))

    for _ in range(20):
        rate_limiting.auth_rate_limit(_fake_request("198.51.100.1"))

    # A different IP has its own, independent budget.
    rate_limiting.auth_rate_limit(_fake_request("198.51.100.2"))
