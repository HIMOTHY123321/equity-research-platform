# ADR 0019: Production & Multi-Tenant Architecture (Phase 16)

## Motivation

Phases 1-15 built a deep, deterministic research pipeline running as a
single local process against a single local user. Phase 16 turns that
into a technically deployable, multi-user product without touching any
research logic: Decision Engine semantics, Signal Validation Gate,
Ranking Gate (still FAIL, ADR 0012, untouched), and anti-lookahead
guarantees are all unchanged.

## Authentication

JWT-based (`app/auth/`), using mature libraries (`bcrypt`, `pyjwt`) rather
than invented cryptography. Stateless by design -- no revocation list
exists yet; disclosed as a deferred improvement (a refresh-token /
revocation architecture would be the natural next step).

## The Watchlist/monitoring-universe split

The single most important architectural decision this phase made: a
per-user personal Watchlist (now genuinely per-user,
`SqlAlchemyWatchlistRepository`, auth-required) is a DIFFERENT thing from
the global monitoring universe (`MonitoringSubscriptionRecord`, which
symbols the Decision Engine actively scans server-wide).

Before this phase, `MonitoringUniverse` seeded itself from "the"
Watchlist -- a single, implicitly-global object. Making Watchlist
per-user broke that assumption outright: a background service constructed
once at process startup (`app.main`'s lifespan, or the standalone
`app.worker`) has no HTTP request and no "current user" to seed from.

Resolution: `MonitoringUniverse` now seeds from a fixed default symbol
list (`DEFAULT_WATCHLIST_SYMBOLS`), completely decoupled from any user's
personal Watchlist. This is the same discipline the spec itself
recommends (global Decision computation stays shared; per-user
preferences are separate) -- applied narrowly, for now, only to
Watchlist. `AlertAcknowledgementRecord`/`AlertPreferenceRecord`/the
global Alert history remain global/shared, disclosed as a deferred
refinement rather than rushed.

## Worker/API split

`Settings.worker_mode` (`combined` / `api` / `worker`) gates whether a
process starts the background monitors. Multi-replica deployments run
every web replica as `api` and exactly one `worker` process
(`python -m app.worker`) -- see `docs/deployment.md`.

## WebSocket authentication

`/api/live/stream` requires `?token=` on the handshake URL (the one
practical way to authenticate a browser WebSocket, which cannot send
custom headers). Resolves its DB session through the same
`app.dependency_overrides` mechanism every other DB-touching dependency
uses, rather than importing `SessionLocal` directly -- the first
implementation attempt used a direct import and silently broke test
isolation (it would have hit the real on-disk dev database in tests).

## Rate limiting

A plain `Depends()` FastAPI dependency (`app/rate_limiting.py`), not
slowapi's `@limiter.limit(...)` decorator -- that decorator was found,
empirically, to break FastAPI's recognition of a POST body parameter's
Pydantic type (a route stopped accepting a JSON body and instead expected
the same field as a query parameter). Disabled outside production by
design, since the shared-process test suite would otherwise flake against
its own signup/login test traffic.

## Errors, request IDs, structured logging

Additive, not breaking: every error response keeps the existing `detail`
field (the frontend already reads `body.detail`) and gains a `request_id`
field alongside it. Production hides exception details; development/test
stay verbose.

## Billing/entitlements

`app/billing/` is an explicitly TEST-MODE-ONLY scaffold: a `plan` column,
a plan -> feature mapping, and a `require_entitlement` dependency that
always re-derives the plan from the authenticated user's own DB row.
No production route is gated by it yet -- gating an already-shipped,
currently-unauthenticated feature (the Validation Lab's AI summary) would
strand users, since the frontend has no login UI at all yet. Deferred and
disclosed rather than forced.

## What Phase 16 does NOT claim

Commercial launch readiness. See `docs/deployment.md`'s "Commercial
launch blockers" section: licensed data, legal review, real billing, a
frontend login UI, per-user alert scoping, and an executed (not just
reviewed) Docker/Postgres smoke test are all still open.
