# ADR 0020: Phase 16.1 -- Multi-User Product Completion

## Motivation

Phase 16 (ADR 0019) made the backend technically multi-tenant (real JWT
auth, per-user Watchlist) but left several gaps the Phase 16 final report
explicitly disclosed as blockers: no frontend login UI, a query-string JWT
on the WebSocket handshake, no session revocation, and alerts/monitoring
still entirely global/shared. Phase 16.1 closes each of these.

## Session transport: HttpOnly cookie, not query-string JWT

`?token=` on the WebSocket handshake URL is gone. Both regular HTTP routes
and the WebSocket handshake now read the SAME HttpOnly, `SameSite=Lax`
session cookie (`app.auth.cookies`, name `amd_session`) -- browsers attach
cookies to a same-site WebSocket handshake automatically, so no URL-borne
secret is needed. `Secure` is set only in production (`Settings.
is_production`); local dev runs over plain HTTP, where a `Secure` cookie
would be silently dropped by the browser. The frontend never reads or
stores the token itself -- no `localStorage`, no client-side JS access
(that's the point of HttpOnly). The `Authorization: Bearer` header is kept
as a fallback, used only by non-browser callers (tests, scripts) that
cannot rely on a cookie jar; an explicit header always wins over an
ambient cookie when both are present (the browser frontend never sends a
header at all, so this never affects it).

## Session lifecycle: JWT + a server-verifiable session row

A JWT alone is stateless -- it stays valid until its own `exp` claim,
which is far too coarse for "log out" or "this user was just disabled" to
take effect immediately. Rather than inventing a new cryptographic
scheme, every issued token now carries a `jti` (JWT ID) claim naming a row
in `user_sessions` (`app.auth.sessions.SqlAlchemyUserSessionRepository`).
`get_current_user` and the WebSocket auth check both require the token to
decode AND its `jti` to name a session row that still exists, is
unexpired, and is unrevoked. `POST /api/auth/logout` revokes exactly the
presented session (never every session a user has); `revoke_all_for_user`
exists for the "disable this account" path. This is still mature-library
JWT (PyJWT/bcrypt), just paired with a conventional revocation-list
pattern -- no custom cryptography.

## Alerts/monitoring: the SYSTEM RESEARCH UNIVERSE vs USER MONITORING SUBSCRIPTIONS

The single most consequential decision this phase made, and the one the
spec asked to be resolved explicitly rather than left implicit.

- **SYSTEM RESEARCH UNIVERSE** (`app.monitoring.universe.MonitoringUniverse`,
  backed by the legacy global `MonitoringSubscriptionRecord` table plus the
  union of every user's monitored symbols) answers "does the background
  Decision Engine compute anything for this symbol at all." It is a
  mechanical union, computed fresh on every scan pass -- there is no
  independent "prune symbols nobody watches anymore" step yet (disclosed
  below).
- **USER MONITORING SUBSCRIPTIONS** (`UserMonitoringSubscriptionRecord`,
  one row per `(user_id, symbol)`) answer "does THIS user want alerts for
  this symbol." `/api/monitoring` (now auth-required) reads and writes
  only the calling user's own rows.
- The single, deterministic `AlertEventRecord` a symbol's transition
  produces is NEVER duplicated per user. Delivery is a pure fan-out:
  `AlertService._record`, on a genuinely new alert (never on a dedup hit),
  calls `AlertRepository.deliver_alert_to_subscribed_users`, which creates
  one `UserAlertDeliveryRecord(user_id, alert_id)` per user with an
  enabled subscription for that symbol (respecting that user's own
  `UserAlertPreferenceRecord` mute setting). `/api/alerts` now lists,
  acknowledges, and counts unread strictly through this delivery table,
  joined back to the shared `AlertEventRecord` for content -- one user can
  never see, acknowledge, or reconfigure another user's deliveries or
  preferences.
- **Research isolation is load-bearing, not incidental**:
  `/api/alerts/prospective-count` and every Forward Validation/Signal Gate
  query still read `AlertEventRecord` directly, never joined through
  `UserAlertDeliveryRecord`. N users monitoring the same symbol produces
  exactly one research observation, not N -- proven by an explicit test
  (`test_research_isolation.py`).

## WebSocket per-user filtering

Phase 16 broadcast `alert_event`/`decision_state_change`/`monitor_status`
frames to every connected client unconditionally (`_UNIVERSE_WIDE_FRAME_
TYPES`). Phase 16.1 filters all three per-connection: `alert_event` only
reaches a connection if that user has a `UserAlertDeliveryRecord` for the
alert's `alert_id`; `decision_state_change`/`monitor_status` only reach a
connection for symbols that user actively monitors. Every other frame
type (quotes, candles, etc.) is unchanged -- filtered to the connection's
own explicit chart subscriptions, as before.

## Frontend

A from-scratch auth experience (`/login`, `/signup`, a session context
provider, Next.js middleware gating every product route on a valid
session cookie, redirect-back via `?next=`, a TopNav account menu, and a
`/settings` page for account/session/alert-preference/monitoring/plan
management). The Watchlist UI now visually separates "in my watchlist"
from "alerts on" -- two independent per-symbol toggles, not one. See
`docs/deployment.md` for what remains a disclosed commercial-launch
blocker rather than a Phase 16.1 gap (licensed data, legal review, real
billing, a Postgres/Docker smoke test not yet executed in this sandbox).

## What Phase 16.1 does NOT claim

The SYSTEM RESEARCH UNIVERSE has no automatic "stop scanning a symbol
nobody monitors anymore" step -- it only ever grows (a symbol added by
one user, later un-monitored by everyone, keeps being scanned until the
legacy global table or a future pruning pass removes it). This matches
the spec's own "architecture MAY eventually remove it... subject to any
system-required research universe" phrasing -- disclosed as future work,
not attempted under time pressure. Commercial launch readiness is
unchanged from ADR 0019/the Phase 16 final report.
