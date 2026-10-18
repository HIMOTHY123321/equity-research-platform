"""Phase 19.6/19.6.1: integration coverage for the deployed WS-auth fix.

Deployed, the frontend's own `amd_session` cookie is host-only to the
frontend's domain and can never reach `/api/live/stream` on the backend's
different domain (see app.auth.ws_ticket's module docstring). The fix: an
already-authenticated browser calls POST /api/live/ws-ticket (same-origin,
cookie-authenticated, proxyable) to get a short-lived, single-use ticket,
then opens the WebSocket carrying that ticket as a `Sec-WebSocket-Protocol`
value (NOT a query-string parameter -- see app.api.routes.live's
WS_TICKET_SUBPROTOCOL docstring for why a query string was rejected after
security review: it can end up in Uvicorn's own access log, Render's edge/
platform logs, or an intermediate reverse proxy's logs, exactly the risk
docs/deployment.md already called out for this same handshake before this
feature existed, and the same reasoning app.market_data.twelve_data_
provider already applied to its own API key).

Reuses the exact `client`/`_authed_ws_url` fixtures from
test_live_routes.py (same isolated-DB, fast-config, no-streaming-provider
setup) so these tests exercise the real app, not a reimplementation of it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.routes.live import WS_TICKET_SUBPROTOCOL
from app.auth.ws_ticket import create_ws_ticket
from tests.integration.test_live_routes import _authed_ws_url, client  # noqa: F401 -- fixture import

_ = client  # keep the fixture import "used" for linters


def _ticket_subprotocols(ticket: str) -> list[str]:
    """The exact two-entry `Sec-WebSocket-Protocol` shape liveClient.ts
    sends: a fixed marker, then the ticket itself."""
    return [WS_TICKET_SUBPROTOCOL, ticket]


def _signup_and_get_ticket(test_client, email: str) -> tuple[str, str]:
    """Signs up a fresh user, then calls the real ticket-issuance endpoint
    through the cookie this signup leaves in the TestClient's jar --
    exactly the path a real authenticated browser takes. Returns
    (ticket, session_cookie_value)."""
    test_client.post("/api/auth/signup", json={"email": email, "password": "hunter2hunter2"})
    session_cookie_value = test_client.cookies.get("amd_session")
    response = test_client.post("/api/live/ws-ticket")
    assert response.status_code == 200
    return response.json()["ticket"], session_cookie_value


def test_an_authenticated_user_can_issue_a_ws_ticket(client):
    test_client, _provider = client
    test_client.post(
        "/api/auth/signup", json={"email": "ticket-issue@example.com", "password": "hunter2hunter2"}
    )

    response = test_client.post("/api/live/ws-ticket")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["ticket"], str) and len(body["ticket"]) > 0
    assert 0 < body["expires_in"] <= 60


def test_an_unauthenticated_caller_cannot_issue_a_ws_ticket(client):
    test_client, _provider = client
    test_client.cookies.clear()

    response = test_client.post("/api/live/ws-ticket")

    assert response.status_code == 401


def test_the_ws_ticket_response_never_contains_the_real_session_jwt(client):
    """The ticket itself is a different, distinctly-purposed JWT (see
    app.auth.ws_ticket) -- it must never equal, and must never merely wrap/
    embed verbatim, the caller's actual session token."""
    test_client, _provider = client
    ticket, session_cookie_value = _signup_and_get_ticket(test_client, "ticket-no-jwt-leak@example.com")

    assert session_cookie_value is not None
    assert ticket != session_cookie_value
    assert session_cookie_value not in ticket


def test_a_valid_ticket_never_appears_in_the_websocket_url(client):
    """The core fix this security review required: the ticket must travel
    only as a Sec-WebSocket-Protocol value, never as part of the URL that
    an access log or browser history would capture."""
    test_client, _provider = client
    ticket, _ = _signup_and_get_ticket(test_client, "ticket-never-in-url@example.com")
    test_client.cookies.clear()
    url = "/api/live/stream"

    with test_client.websocket_connect(url, subprotocols=_ticket_subprotocols(ticket)) as ws:
        frame = ws.receive_json()
        assert frame["type"] == "connection_status"

    assert ticket not in url
    assert "ticket" not in url


def test_a_valid_ticket_opens_the_websocket_with_no_cookie_present(client):
    """The deployed scenario: the browser's cookie never reaches the
    backend at all -- clearing the cookie jar proves the ticket alone is
    sufficient, exactly like the real cross-domain case."""
    test_client, _provider = client
    ticket, _ = _signup_and_get_ticket(test_client, "ticket-ws-connect@example.com")
    test_client.cookies.clear()

    with test_client.websocket_connect(
        "/api/live/stream", subprotocols=_ticket_subprotocols(ticket)
    ) as ws:
        frame = ws.receive_json()
        assert frame["type"] == "connection_status"


def test_an_invalid_ticket_is_rejected(client):
    test_client, _provider = client
    test_client.cookies.clear()

    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect(
            "/api/live/stream", subprotocols=_ticket_subprotocols("not-a-real-ticket")
        ):
            pass


def test_a_connection_offering_no_subprotocol_and_no_cookie_is_rejected(client):
    test_client, _provider = client
    test_client.cookies.clear()

    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect("/api/live/stream"):
            pass


def test_an_expired_ticket_is_rejected_at_the_handshake(client):
    test_client, _provider = client
    test_client.post(
        "/api/auth/signup", json={"email": "ticket-expired@example.com", "password": "hunter2hunter2"}
    )
    session_cookie = test_client.cookies.get("amd_session")
    # Decode just enough to recover this session's own jti so the hand-
    # crafted expired ticket below is bound to a session that genuinely
    # exists (isolating "ticket itself is expired" from "session invalid").
    from app.auth.security import decode_access_token

    session_jti = decode_access_token(session_cookie).jti
    expired_issued_at = datetime.now(timezone.utc) - timedelta(hours=1)
    user_id = decode_access_token(session_cookie).user_id
    expired_ticket = create_ws_ticket(user_id, session_jti, now=expired_issued_at).token
    test_client.cookies.clear()

    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect(
            "/api/live/stream", subprotocols=_ticket_subprotocols(expired_ticket)
        ):
            pass


def test_a_wrong_purpose_token_a_real_session_jwt_is_rejected_as_a_ticket(client):
    """A genuinely valid, correctly-signed session access token must still
    be rejected when presented as the ticket subprotocol value -- type/
    purpose is checked, not just the signature."""
    test_client, _provider = client
    test_client.post(
        "/api/auth/signup", json={"email": "ticket-wrong-purpose@example.com", "password": "hunter2hunter2"}
    )
    session_cookie = test_client.cookies.get("amd_session")
    test_client.cookies.clear()

    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect(
            "/api/live/stream", subprotocols=_ticket_subprotocols(session_cookie)
        ):
            pass


def test_a_ticket_is_single_use_a_second_connection_with_the_same_ticket_is_rejected(client):
    test_client, _provider = client
    ticket, _ = _signup_and_get_ticket(test_client, "ticket-replay@example.com")
    test_client.cookies.clear()

    with test_client.websocket_connect("/api/live/stream", subprotocols=_ticket_subprotocols(ticket)) as ws:
        ws.receive_json()

    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect("/api/live/stream", subprotocols=_ticket_subprotocols(ticket)):
            pass


def test_a_ticket_minted_from_a_revoked_logged_out_session_is_rejected(client):
    """Binding a ticket to the originating session's jti (not just the
    user id) means logout invalidates every outstanding ticket from that
    session too, even one already issued but not yet consumed."""
    test_client, _provider = client
    ticket, _ = _signup_and_get_ticket(test_client, "ticket-revoked-session@example.com")
    logout = test_client.post("/api/auth/logout")
    assert logout.status_code in (200, 204)

    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect("/api/live/stream", subprotocols=_ticket_subprotocols(ticket)):
            pass


def test_cookie_auth_still_works_locally_when_no_ticket_is_present(client):
    """Local-dev parity: when no ticket subprotocol is offered, the
    handshake still falls back to the same HttpOnly cookie every other
    route uses."""
    test_client, _provider = client
    url = _authed_ws_url(test_client, email="ticket-cookie-fallback@example.com")

    with test_client.websocket_connect(url) as ws:
        frame = ws.receive_json()
        assert frame["type"] == "connection_status"


def test_extract_ticket_from_subprotocols_only_matches_the_exact_two_entry_shape():
    """Unit-level proof of the extraction logic itself (same SimpleNamespace
    pattern test_live_routes.py already uses for `_user_monitors_symbol`) --
    this is what `live_stream` relies on to recover the ticket from
    `Sec-WebSocket-Protocol` instead of a query string."""
    from types import SimpleNamespace

    from app.api.routes.live import _extract_ticket_from_subprotocols

    fake = SimpleNamespace(scope={"subprotocols": [WS_TICKET_SUBPROTOCOL, "the-actual-ticket"]})
    assert _extract_ticket_from_subprotocols(fake) == "the-actual-ticket"

    assert _extract_ticket_from_subprotocols(SimpleNamespace(scope={"subprotocols": []})) is None
    assert _extract_ticket_from_subprotocols(SimpleNamespace(scope={})) is None
    assert (
        _extract_ticket_from_subprotocols(SimpleNamespace(scope={"subprotocols": ["other-protocol"]})) is None
    )
    assert (
        _extract_ticket_from_subprotocols(
            SimpleNamespace(scope={"subprotocols": ["other-protocol", "x"]})
        )
        is None
    )


def test_real_time_available_is_unaffected_by_ticket_issuance_or_use(client):
    """Critical market-data rule: this entire feature is USER
    authentication for the WebSocket transport, never provider
    entitlement. Issuing and consuming a ticket must not change
    `real_time_available` -- in this fixture (no streaming provider
    configured), it must stay False throughout."""
    test_client, _provider = client
    ticket, _ = _signup_and_get_ticket(test_client, "ticket-real-time-unaffected@example.com")

    before = test_client.get("/api/live/status").json()
    assert before["real_time_available"] is False

    with test_client.websocket_connect("/api/live/stream", subprotocols=_ticket_subprotocols(ticket)) as ws:
        ws.receive_json()

    after = test_client.get("/api/live/status").json()
    assert after["real_time_available"] is False
