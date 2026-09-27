"""Phase 16 (§20/§21/§22): request correlation IDs, structured request
logging, and a standardized (but backward-compatible) error envelope.

Kept backward-compatible on purpose: every existing route already raises
`HTTPException(detail=...)`, and the frontend already reads
`body.detail` (apps/web/src/lib/api.ts) -- this module ADDS a
`request_id` field alongside `detail` rather than renaming/nesting it,
so no existing route or frontend call site needs to change.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Environment, get_settings

logger = logging.getLogger("app.request")

_REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generates one correlation id per request (or reuses an inbound
    `X-Request-ID` from a trusted upstream proxy/load balancer), exposes
    it as `request.state.request_id`, and echoes it back on the response
    so a client/log line/error body can all be tied to the same request."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[_REQUEST_ID_HEADER] = request_id
        return response


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """One structured log line per request: method, path, status, latency,
    request_id -- never the request/response body (which could contain a
    password on /api/auth/login, or a session token), never headers
    (which could contain the Authorization bearer token itself)."""

    async def dispatch(self, request: Request, call_next):
        started_at = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - started_at) * 1000
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        return response


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "unknown"


def exception_detail_for_response(exc: Exception, environment: Environment) -> str:
    """Pulled out as its own pure function so the redaction decision is
    directly unit-testable without needing to mutate the process-wide
    cached `get_settings()` singleton mid-test-session."""
    if environment in (Environment.DEVELOPMENT, Environment.TEST):
        return f"{type(exc).__name__}: {exc}"
    return "Internal server error"


def install_error_handlers(app: FastAPI) -> None:
    """Registers handlers that add `request_id` to every error response
    without changing the existing `detail` shape, and that hide internal
    exception details in production (development/test stay verbose for
    debuggability) -- see §20/§113/§124."""

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": _request_id(request)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "request_id": _request_id(request)},
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.exception("Unhandled exception (request_id=%s)", request_id)
        # Never leak a traceback, stack path, DB URL, or secret in a
        # production response body -- the real detail is in the log line
        # above, keyed by the same request_id.
        detail = exception_detail_for_response(exc, get_settings().environment)
        return JSONResponse(status_code=500, content={"detail": detail, "request_id": request_id})
