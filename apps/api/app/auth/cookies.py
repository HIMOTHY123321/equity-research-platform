"""Phase 16.1: the single HttpOnly session cookie both regular HTTP routes
and the WebSocket handshake read (see app.api.routes.live) -- never
readable by frontend JavaScript, never placed in a URL/query string, never
written to browser localStorage. `Secure` is only set in production
(Settings.is_production) since local development runs over plain HTTP,
where a browser silently drops a `Secure` cookie entirely."""

from __future__ import annotations

from fastapi import Response

from app.config import Settings

SESSION_COOKIE_NAME = "amd_session"


def set_session_cookie(response: Response, token: str, *, settings: Settings, max_age_seconds: int) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age_seconds,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, *, settings: Settings) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
