# Deployment Guide (Phase 16)

This document covers what it takes to run AI Market Desk as a real,
multi-user, production-topology deployment. It reflects the actual state
of the codebase after Phase 16 -- it does not describe aspirational
infrastructure that hasn't been built.

## Readiness levels

- **LOCAL DEVELOPMENT** -- `npm run dev` + `uvicorn --reload`, SQLite,
  yfinance, mock AI provider. Always available, no setup required.
- **PRODUCTION TECHNICALLY READY** -- what this phase delivers: real auth,
  server-side authorization, per-user data isolation, Postgres + Alembic
  migrations, a worker/api process split, authenticated WebSockets,
  fail-fast config validation, rate limiting, structured logging,
  standardized errors, health/readiness endpoints, a billing-ready
  entitlement scaffold, Dockerfiles, docker-compose, and CI.
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

See `apps/api/.env.example` for the full, authoritative list with
comments. Key groups: app/session (`SECRET_KEY`, `JWT_ALGORITHM`,
`ACCESS_TOKEN_TTL_MINUTES`), database (`DATABASE_URL`), market/news/AI
provider selection and credentials, scheduling.

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

Every Phase 13-16 table (Decision Engine, alerts, monitoring, validation,
auth) is now covered by `alembic/versions/0009_...py` and
`0010_user_plan.py` -- `Base.metadata.create_all(checkfirst=True)` at
runtime is a dev/test convenience only and is a no-op once migrations
have already created the tables.

## Running locally against Postgres (docker-compose)

```bash
docker compose up --build
docker compose run --rm api alembic upgrade head
```

This starts Postgres + `api` (worker_mode=api) + a single `worker` +
`web`, the same topology a real multi-replica deployment uses. The
`SECRET_KEY` in `docker-compose.yml` is a throwaway local value -- never
reuse it.

**Not yet verified in this repository**: Docker was not available in the
sandbox this phase was built in, so the compose stack has been reviewed
for correctness (Dockerfiles, service wiring, migration path) but not
actually executed end-to-end. Run `docker compose up --build` once in a
Docker-capable environment before relying on it for a real deployment.

## Authentication & sessions

JWT-based, stateless (`app/auth/`). No server-side revocation list exists
yet -- "logout" is a client-side token discard. A refresh-token /
revocation architecture is a disclosed, deferred improvement.

## Authorization & multi-tenancy

- Watchlist is fully per-user (`app.watchlist.repository
  .SqlAlchemyWatchlistRepository`), enforced via `get_current_user` --
  every query is scoped to the authenticated user's id server-side.
- The global monitoring universe (which symbols the Decision Engine
  actively scans) and Alert history remain global/shared by design --
  see `app/monitoring/universe.py`'s own docstring. Per-user alert
  delivery/acknowledgement scoping is a disclosed, deferred refinement
  (`AlertAcknowledgementRecord`/`AlertPreferenceRecord` have no
  `user_id` yet).

## WebSocket authentication

`/api/live/stream` requires `?token=<valid JWT>` on the handshake URL
(browsers cannot send custom headers on a WebSocket handshake). The
frame stream itself remains global/shared content today, not yet
filtered per user -- see the same deferred-refinement note above.

## Rate limiting

`app/rate_limiting.py` gates `/api/auth/signup` and `/api/auth/login`
(20/minute per IP), enforced only when `ENVIRONMENT=production` --
disabled elsewhere so the shared-process test suite never trips it. See
that module's docstring for the full rationale.

## Billing / entitlements

`app/billing/` is TEST-MODE ONLY -- no real payment provider is wired.
`User.plan` defaults to `free`; an admin-only endpoint
(`POST /api/admin/users/{id}/plan`) can promote a user to `pro` for
testing. `require_entitlement(feature)` enforces server-side, never
trusting a client-supplied plan claim. No production route is gated by
an entitlement yet (the Validation Lab's AI summary is a natural
candidate, deferred until the frontend has a login UI -- see
"Commercial launch blockers").

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
- [ ] `SECRET_KEY` is a real, unique, high-entropy value
- [ ] `DATABASE_URL` points at managed Postgres with backups enabled
- [ ] `MARKET_DATA_PROVIDER`/`NEWS_PROVIDER` point at licensed providers
- [ ] `CORS_ORIGINS` set to the real frontend origin(s) only
- [ ] Exactly one `worker_mode=worker` process running; all others `api`
- [ ] `/health/ready` returns 200 before traffic is routed to a replica
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
  pages were built this phase) and need counsel review before launch.
- **Real billing** -- Stripe (or equivalent) integration, real product/
  price objects, webhook handling for subscription lifecycle, and
  removing the test-mode-only admin plan-change endpoint (or locking it
  down further) before any real customer exists.
- **Frontend authentication UI** -- no login/signup page exists in
  `apps/web` yet; the backend auth API is complete and tested, but a user
  cannot currently sign up through the running application.
- **Per-user alert/monitoring scoping** -- disclosed above as deferred;
  acceptable for a single-tenant-feeling research tool today, not for a
  commercial multi-tenant product where users expect private alert
  preferences.
- **Docker/Postgres smoke test** -- reviewed but not executed end-to-end
  (no Docker available in the environment this phase was built in).
- **Security review** -- this phase added defensive tests (auth bypass,
  cross-tenant isolation, error redaction) but has not had an external
  security review or penetration test.
