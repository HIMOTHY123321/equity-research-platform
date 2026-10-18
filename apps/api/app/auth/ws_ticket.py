"""Phase 19.6/19.6.1: short-lived, single-purpose WebSocket auth tickets.

Deployed, the frontend and backend are genuinely different hosts
(ai-market-desk-web.onrender.com vs ai-market-desk.onrender.com). The
`amd_session` cookie the frontend mints for itself (see
app/../apps/web/src/lib/auth-proxy.ts) is host-only to the FRONTEND's own
domain and can never reach the backend's WebSocket handshake
(`websocket.cookies.get(...)` in app.api.routes.live.live_stream) -- raw
browser WebSockets cannot be routed through the same-origin REST proxy the
way normal fetch() calls are, and a cross-domain cookie is explicitly
forbidden.

Instead, an already-authenticated browser requests a ticket through the
normal (same-origin, cookie-authenticated) REST path, then opens the
WebSocket directly to the backend carrying ONLY that ticket -- never the
real session JWT. Phase 19.6.1 (post security review): the ticket travels
as a `Sec-WebSocket-Protocol` handshake value, NOT a query parameter --
see app.api.routes.live.WS_TICKET_SUBPROTOCOL for why a query string was
rejected (it can end up in Uvicorn's own access log, Render's edge/
platform logs, or an intermediate reverse proxy's logs; docs/
deployment.md already documented "nothing in this handshake's URL" as an
invariant before this feature existed). The ticket:

- is signed with the same `settings.secret_key`/`jwt_algorithm` every other
  session token in this codebase uses (app.auth.security) -- no new secret
  infrastructure.
- carries a distinct `type` claim ("ws_stream_ticket") so it can never be
  replayed against any other endpoint that accepts a session token, and a
  normal session token can never be replayed here.
- is bound to the ORIGINAL session's `jti`, not just the user id -- a
  logout (which revokes that session row, see app.auth.sessions) also
  invalidates every outstanding ticket minted from it, even one already
  issued but not yet consumed.
- lives for WS_TICKET_TTL_SECONDS (short: just long enough for the browser
  to receive the HTTP response and open the socket) and is single-use,
  enforced by `_ReplayGuard` below.

Replay-guard limitation (documented, not fixed here -- see
docs/deployment.md's "Known limitation" note): `_ReplayGuard` is
in-process memory, not a shared store. It is correct for a single API
process/instance; if this API ever runs as more than one horizontally-
scaled replica, a ticket could theoretically be replayed once against a
DIFFERENT replica before its ~45s expiry, since each replica tracks
"already used" tickets independently. Deliberately out of scope here --
no Redis/shared persistence was introduced to close this -- because every
other rejection (signature, expiry, purpose/type, revoked session,
inactive user) still applies regardless of replica count, and the
exposure window is both short-lived and requires an attacker to already
hold a valid ticket (itself requiring a valid, unrevoked session).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt

from app.auth.security import InvalidTokenError
from app.config import Settings, get_settings

_WS_TICKET_TYPE = "ws_stream_ticket"

# Deliberately short: a ticket is minted, sent over one HTTP response, and
# consumed by one WebSocket handshake within the same page load -- there is
# no legitimate reason for one to still be unused 60 seconds later.
WS_TICKET_TTL_SECONDS = 45


@dataclass(frozen=True)
class IssuedWsTicket:
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class WsTicketPayload:
    user_id: UUID
    session_jti: str
    ticket_jti: str
    expires_at: datetime


def create_ws_ticket(
    user_id: UUID, session_jti: str, *, settings: Optional[Settings] = None, now: Optional[datetime] = None
) -> IssuedWsTicket:
    settings = settings or get_settings()
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=WS_TICKET_TTL_SECONDS)
    ticket_jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "session": session_jti,
        "type": _WS_TICKET_TYPE,
        "jti": ticket_jti,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return IssuedWsTicket(token=token, expires_at=expires_at)


def decode_ws_ticket(token: str, *, settings: Optional[Settings] = None) -> WsTicketPayload:
    """Raises InvalidTokenError for anything malformed, expired, unsigned,
    or not actually a ws-ticket (e.g. a real session JWT presented here --
    `type` differs, so it is rejected exactly like garbage input)."""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Malformed, expired, or unsigned ticket") from exc

    if payload.get("type") != _WS_TICKET_TYPE:
        raise InvalidTokenError("Wrong ticket purpose")

    subject = payload.get("sub")
    session_jti = payload.get("session")
    ticket_jti = payload.get("jti")
    exp = payload.get("exp")
    if not subject or not session_jti or not ticket_jti or exp is None:
        raise InvalidTokenError("Missing required ticket claims")

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError("Subject claim is not a valid user id") from exc

    return WsTicketPayload(
        user_id=user_id,
        session_jti=session_jti,
        ticket_jti=ticket_jti,
        expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
    )


class _ReplayGuard:
    """Process-local single-use enforcement. No new persistence layer: a
    ticket's own lifetime is seconds, so an in-memory set bounded by "every
    ticket issued in the last WS_TICKET_TTL_SECONDS" is both correct for a
    single API process and cheap to sweep. Does not protect against replay
    across multiple horizontally-scaled API processes (a real limitation,
    documented rather than silently assumed away) -- the signature,
    expiry, and session-liveness checks still apply there regardless."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, datetime] = {}

    def consume(self, ticket_jti: str, expires_at: datetime, now: datetime) -> bool:
        with self._lock:
            for jti in [j for j, exp in self._seen.items() if exp <= now]:
                del self._seen[jti]
            if ticket_jti in self._seen:
                return False
            self._seen[ticket_jti] = expires_at
            return True


_replay_guard = _ReplayGuard()


def consume_ws_ticket_once(ticket_jti: str, expires_at: datetime, *, now: Optional[datetime] = None) -> bool:
    """Returns True the first time this ticket_jti is presented (and marks
    it used), False on any later attempt -- a second connection attempt
    with the same ticket must be rejected even though it is still within
    its signature-valid expiry window."""
    return _replay_guard.consume(ticket_jti, expires_at, now or datetime.now(timezone.utc))
