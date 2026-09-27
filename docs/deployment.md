# Deployment Guide (Phase 16.1)

This document covers what it takes to run AI Market Desk as a real,
multi-user, production-topology deployment. It reflects the actual state
of the codebase after Phase 16.1 -- it does not describe aspirational
infrastructure that hasn't been built.

## Readiness levels

- **LOCAL DEVELOPMENT** -- `npm run dev` + `uvicorn --reload`, SQLite,
  yfinance, mock AI provider. Always available, no setup required.
- **STAGING READY** -- a real, deployable multi-user application: sign
  up/sign in through the actual UI, per-user Watchlist/monitoring/alerts,
  a session cookie that survives revocation/expiration, and an
  authenticated, per-user-filtered WebSocket. Suitable for a real staging
  environment with real (non-production) users testing the product.
- **PRODUCTION TECHNICALLY READY** -- STAGING READY plus Postgres +
  Alembic migrations, a worker/api process split, fail-fast config
  validation, rate limiting, structured logging, standardized errors,
  health/readiness endpoints, a billing-ready entitlement scaffold,
  Dockerfiles, docker-compose, and CI. Architecturally ready; deployment
  smoke pending (see "Commercial launch blockers" -- the docker-compose
  Postgres stack has been reviewed, not executed, in this sandbox).
- **COMMERCIAL LAUNCH READY** -- NOT claimed by this phase. See
  "Commercial launch blockers" below.

## Environments

Set `ENVIRONMENT` to one of `development` (default) / `test` / `staging`
/ `production`. See `app/config.py::Settings._validate_production_safety`
for the exact fail-fast rules production triggers -- summarized:

- `SECRET_KEY` must be set and must not be the development placeholder.
- `DATABASE_URL` must not be SQLite.
- `MARKET_DATA_PROVIDER` and `NEWS_PROVIDER` must not be `yfinance`.
- `CORS_ORIGINS` must not be empty or `*`.

A production process that violates any of these refuses to start --
there is no silent fallback.

## Environment variables

See `apps/api/.env.example` for the full, authoritative backend list with
comments, and `apps/web/.env.example` for the frontend. Key groups:
app/session (`SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_TTL_MINUTES`),
database (`DATABASE_URL`), market/news/AI provider selection and
credentials, scheduling.

**`SESSION_JWT_SECRET` (frontend, Phase 16.1) MUST equal the backend's
`SECRET_KEY` exactly.** `apps/web/proxy.ts` verifies the session cookie's
JWT signature locally (fast client-side route gate, no DB round trip)
using this value; a mismatch means every request looks unauthenticated
and every product route redirects to `/login` even with a valid session.
Both default to the same obviously-fake development placeholder so local
dev needs no extra configuration -- production must override both, to
the same real secret.

`WORKER_MODE` (`combined` | `api` | `worker`) controls whether this
process starts the background monitors -- see the next section.

## Worker model

Background services (`LiveMarketService`, `RecomputationEngine`,
`ForecastMonitor`, `NewsMonitor`, `MonitoringService`) must run exactly
ONCE per environment, never once per web replica (they'd duplicate every
global scan).

- Single-instance deployment: leave `WORKER_MODE=combined` (default).
- Multi-replica deployment: set every web replica to `WORKER_MODE=api`
  and run exactly one additional process with `python -m app.worker`
  (see `apps/api/Dockerfile.worker`).

## Database & migrations

Production must use Postgres (`DATABASE_URL=postgresql+psycopg://...`).
SQLite remains supported for local dev/test only.

```bash
# apply all migrations
alembic upgrade head

# check current revision
alembic current

# rollback one migration (only if you understand what it drops --
# see each migration's own downgrade())
alembic downgrade -1
```

Every Phase 13-16.1 table (Decision Engine, alerts, monitoring,
validation, auth, sessions, per-user monitoring/delivery/preferences) is
covered by migrations `0009` through `0011` --
`Base.metadata.create_all(checkfirst=True)` at runtime is a dev/test
convenience only and is a no-op once migrations have already created the
tables.

## Running locally against Postgres (docker-compose)

```bash
docker compose up --build
docker compose run --rm api alembic upgrade head
```

This starts Postgres + `api` (worker_mode=api) + a single `worker` +
`web`, the same topology a real multi-replica deployment uses. The
`SECRET_KEY` in `docker-compose.yml` is a throwaway local value -- never
reuse it, and remember `apps/web`'s `SESSION_JWT_SECRET` must match it.

**PostgreSQL smoke test -- still not executed in this repository.**
Docker is unavailable in the sandbox this and the prior phase were built
in (`docker --version` → command not found). The compose stack has been
reviewed for correctness (Dockerfiles, service wiring, migration path,
env var propagation) but never run end-to-end. Before relying on it for
a real deployment, run the following in a Docker-capable environment and
confirm every step succeeds against a genuinely empty Postgres database:

```bash
docker compose up --build -d
docker compose run --rm api alembic upgrade head
curl -f http://localhost:8000/health/ready
# Sign up two users, verify Watchlist/monitoring/alerts isolation between
# them (see the User A / User B checklist this phase's final report
# documents), then:
docker compose down -v
```

This remains an explicit deployment blocker, not silently marked done.

## Authentication & sessions (Phase 16.1)

JWT-based (`app/auth/`), transported via an HttpOnly, `SameSite=Lax`
session cookie (`amd_session`, `app/auth/cookies.py`) -- the frontend
never reads or stores the token itself. `Authorization: Bearer` is kept
as a fallback for non-browser callers (tests, scripts); an explicit
header always wins over the ambient cookie when both are present.

Every issued token carries a `jti` claim naming a row in `user_sessions`
(`app/auth/sessions.py`) -- `get_current_user` and the WebSocket auth
check both require that row to still exist, be unexpired, and be
unrevoked, not just a valid signature. `POST /api/auth/logout` revokes
exactly the presented session. There is still no refresh-token rotation
or "revoke all my other sessions" UI -- a real access-token TTL
(`ACCESS_TOKEN_TTL_MINUTES`, default 24h) is the outer bound; disclosed
as a reasonable, deferred future improvement rather than a gap in the
core revocation mechanism itself.

## Authorization & multi-tenancy (Phase 16.1)

- Watchlist is fully per-user (`app.watchlist.repository
  .SqlAlchemyWatchlistRepository`), enforced via `get_current_user` --
  every query is scoped to the authenticated user's id server-side.
- **Monitoring is fully per-user** (`UserMonitoringSubscriptionRecord`,
  `/api/monitoring`, auth-required) -- distinct from the SYSTEM RESEARCH
  UNIVERSE (`app.monitoring.universe.MonitoringUniverse`), which decides
  which symbols get background computation at all (the union of a fixed
  default set and every symbol at least one user monitors). See
  `docs/decisions/0020-multi-user-product-completion.md`.
- **Alert delivery is fully per-user** (`UserAlertDeliveryRecord`,
  `/api/alerts`, auth-required) -- a fan-out of the single, shared,
  never-duplicated `AlertEventRecord` a symbol's transition produces.
  `/api/alerts/prospective-count` remains deliberately global/
  unauthenticated: Forward Validation research counts must never inflate
  because more users started monitoring the same symbol.
- The SYSTEM RESEARCH UNIVERSE has no automatic pruning step yet -- a
  symbol added by one user, later un-monitored by everyone, keeps being
  scanned until removed from the legacy global table. Disclosed, deferred
  future work, not a correctness gap (it only ever over-scans, never
  leaks data).

## WebSocket authentication (Phase 16.1)

`/api/live/stream` authenticates off the same HttpOnly session cookie
every HTTP route uses -- browsers attach cookies to a same-site WebSocket
handshake automatically, so no token ever appears in the URL, browser
history, or server access logs. A query-string `?token=` is explicitly
rejected even if it names a genuinely valid token.

Per-connection frame filtering: `alert_event` frames only reach a
connection if that user has a delivery for the specific alert;
`decision_state_change`/`monitor_status` frames only reach a connection
for symbols that user actively monitors. Every other frame type (quotes,
candles) is unchanged -- filtered to the connection's own explicit chart
subscriptions.

## Rate limiting

`app/rate_limiting.py` gates `/api/auth/signup` and `/api/auth/login`
(20/minute per IP), enforced only when `ENVIRONMENT=production` --
disabled elsewhere so the shared-process test suite never trips it. See
that module's docstring for the full rationale.

## Billing / entitlements

`app/billing/` is TEST-MODE ONLY -- no real payment provider is wired.
`User.plan` defaults to `free`; an admin-only endpoint
(`POST /api/admin/users/{id}/plan`) can promote a user to `pro` for
testing. `require_entitlement(feature)` enforces server-side, always
re-deriving the plan from the authenticated user's own DB row -- never
trusting a client-supplied plan claim (proven by test). No production
route is gated by an entitlement yet.

## Observability

- Every response carries `X-Request-ID` (generated or echoed from an
  inbound proxy header) and the same id appears in error response bodies
  (`request_id` field, alongside the existing `detail` field -- no
  breaking rename).
- One structured log line per request (method/path/status/duration/
  request_id), never body/header contents.
- `/health/live` (process alive), `/health/ready` (DB reachable),
  `/api/system/status` (provider honesty -- confirms whether yfinance is
  in use, never returns a credential).

## CI

`.github/workflows/ci.yml` runs backend pytest + ruff, and frontend
vitest + ESLint + tsc + production build, on every push/PR. Live-provider
network smoke tests and the docker-compose Postgres smoke test are
deliberately excluded from ordinary CI (see the workflow file's own
comment) and remain manual/deferred.

## Production release checklist

- [ ] Migrations applied (`alembic upgrade head` against the real DB)
- [ ] `ENVIRONMENT=production` and every fail-fast check passes on boot
- [ ] `SECRET_KEY` is a real, unique, high-entropy value, and the
      frontend's `SESSION_JWT_SECRET` matches it exactly
- [ ] `DATABASE_URL` points at managed Postgres with backups enabled
- [ ] `MARKET_DATA_PROVIDER`/`NEWS_PROVIDER` point at licensed providers
- [ ] `CORS_ORIGINS` set to the real frontend origin(s) only
- [ ] Exactly one `worker_mode=worker` process running; all others `api`
- [ ] `/health/ready` returns 200 before traffic is routed to a replica
- [ ] Docker/Postgres smoke test executed end-to-end at least once
      (see above -- still outstanding as of this phase)
- [ ] Error tracking (Sentry or equivalent) wired if desired -- no
      abstraction point exists for this yet (disclosed, deferred)
- [ ] Backups configured on the managed Postgres instance
- [ ] Signal Validation Gate / Ranking Gate statuses still visible and
      unchanged by any of the above

## Commercial launch blockers

Technically ready is not commercially ready. Before charging real money
or representing this as a licensed product:

- **Licensed real-time market data** -- yfinance must never be the
  production feed (enforced at startup); a real Alpaca/Massive/other
  contract is required.
- **Licensed news data** -- same principle for `NEWS_PROVIDER`.
- **Legal review** -- Terms of Service, Privacy Policy, and the research
  disclaimer are not present in this codebase at all yet (no placeholder
  pages were built) and need counsel review before launch.
- **Real billing** -- Stripe (or equivalent) integration, real product/
  price objects, webhook handling for subscription lifecycle, and
  removing the test-mode-only admin plan-change endpoint (or locking it
  down further) before any real customer exists.
- **Docker/Postgres smoke test** -- reviewed but not executed end-to-end
  (no Docker available in the environment this and the prior phase were
  built in).
- **Security review** -- this phase added defensive tests (auth bypass,
  cross-tenant isolation, session revocation, error redaction) but has
  not had an external security review or penetration test.
- **Session lifecycle hardening** -- no refresh-token rotation, no
  "sign out everywhere" UI, no device/session management page. Access
  tokens are bounded by `ACCESS_TOKEN_TTL_MINUTES` and are individually
  revocable server-side, which is sufficient for staging/early
  production use but not yet a full session-management product surface.
- **SYSTEM RESEARCH UNIVERSE pruning** -- symbols only ever accumulate
  into the global scan set; there's no "stop scanning a symbol nobody
  monitors anymore" step yet (cost/scale concern at larger user counts,
  not a correctness or data-isolation issue).
