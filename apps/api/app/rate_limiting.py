"""Phase 16 (§18/§19): request-rate limiting for public, unauthenticated-
abuse-prone endpoints (signup/login) -- the only category this phase adds
limits to. Other endpoint classes (symbol search, candles, research, AI
summaries) are left unlimited for now; this is a reusable FastAPI
dependency, so adding a limit to another route later needs no new
plumbing, just `Depends(auth_rate_limit)` (or a differently-configured
instance of RateLimiter).

Deliberately a plain `Depends()` dependency, NOT the `@limiter.limit(...)`
decorator slowapi ships -- that decorator does not reliably preserve a
route function's parameter signature across FastAPI/Starlette versions
(observed here: it caused FastAPI to stop recognizing a POST body
parameter's Pydantic type, turning it into a 422 "missing query param"
error). A plain dependency has no such risk since it participates in
FastAPI's normal dependency-injection signature the same way as every
other `Depends()` in this codebase.

Deliberately DISABLED outside production (see `_ENABLED` below).
Rationale: this limiter counts requests against one process-wide in-memory
store for the lifetime of the Python process -- in this codebase's test
suite, `app.main.app` is a single module-level FastAPI instance imported
once and reused across the entire pytest session, so a limit tight enough
to matter for real abuse would also count every test file's signup/login
calls against the same shared window and could fail unrelated tests
non-deterministically depending on run order/timing. This mirrors an
established discipline in this codebase (Phase 14.1's background-service
test isolation): a control that is only meaningful in production must not
silently destabilize the test suite.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from limits import RateLimitItemPerMinute
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

from app.config import Environment, get_settings

_ENABLED = get_settings().environment == Environment.PRODUCTION

_storage = MemoryStorage()
_strategy = FixedWindowRateLimiter(_storage)

#: Generous enough for a real user who mistypes a password a few times,
#: tight enough to blunt a scripted credential-stuffing attempt against
#: one IP.
_AUTH_LIMIT = RateLimitItemPerMinute(20)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def auth_rate_limit(request: Request) -> None:
    """FastAPI dependency for POST /api/auth/signup and /api/auth/login."""
    if not _ENABLED:
        return
    key = f"auth:{_client_ip(request)}"
    if not _strategy.hit(_AUTH_LIMIT, key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again shortly.",
            headers={"Retry-After": "60"},
        )
