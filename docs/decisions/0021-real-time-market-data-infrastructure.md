# ADR 0021: Phase 17 -- Real-Time Market Data Infrastructure & Licensed-Provider Readiness

## Motivation

Phase 12/12.1/12.2 already built a genuine streaming pipeline
(`LiveMarketService`, provider capability abstraction, forming/completed
candle semantics) when a streaming-capable provider (Massive) is
configured. What Phase 17 closes is everything that made claiming "REAL
TIME" to a user technically premature even with that pipeline running:
there was no concept of account-level *entitlement* separate from
provider-code capability, no reconnect gap-fill, no WS frame versioning,
no honest dev-only way to preview live-chart UX without a real provider
account, and no explicit guarantee that such a dev tool could never
contaminate research/validation counts.

**Binding constraint carried through every decision below:** this
product's owner is a minor. Nothing in this phase may depend on the owner
personally entering an adult commercial contract, misrepresenting age, or
using a personal/noncommercial entitlement for commercial redistribution.
The objective is a complete, honest technical architecture that a later
eligible contracting party (parent/guardian, adult business entity, or the
owner once legally eligible) can activate by setting configuration --
never by code changes.

## Market Data Entitlement: a new, deliberately separate concept

`app.live.entitlement.MarketDataEntitlement` / `EntitlementStatus`
(`ENTITLED / NOT_ENTITLED / UNKNOWN / MISCONFIGURED`) answers one question
only: does the configured provider ACCOUNT carry real-time streaming
access. This is explicitly distinct from two things this codebase could
otherwise conflate it with:

- `app.market_data.capabilities.ProviderCapabilities` -- a fact about the
  provider *implementation*, true regardless of which account's key is
  configured.
- `app.billing.entitlements` -- gates in-app *features* (e.g. the
  Validation Lab AI summary) by the authenticated *user's* plan. A PRO app
  subscriber does not grant the backend a licensed exchange feed.

`resolve_streaming_entitlement()` is the one function that decides this,
and it is deliberately conservative: a configured API key that
authenticates successfully is **not** sufficient evidence of entitlement
(Massive's API exposes no "what tier is this key" call). Only an explicit
operator-set `MASSIVE_STREAMING_ENTITLED=true`, set after an eligible
contracting party has confirmed the account's real plan, produces
`ENTITLED`. Unset defaults to `UNKNOWN`, never an assumed `true`.

`LiveMarketService.real_time_available()` requires BOTH a genuinely active
streaming connection (`is_streaming()`, the pre-existing technical check)
AND `entitlement.confirmed` -- this is the one function the frontend's
REAL TIME indicator is driven from (`/api/live/status`'s
`real_time_available` field). `is_streaming()` itself is left
un-gated and kept as a diagnostic-only signal (still useful to know a
connection is technically up even when not entitled).

## Gap-fill on reconnect: REST backfill of closed bars only, gated by outage length

`LiveMarketService._gap_fill_symbol` fires only when a reconnect follows a
genuine outage (`gap_seconds >= config.gap_fill_min_gap_seconds`, default
5s) -- a fast, sub-second blip-and-recover never touches REST at all,
preserving the pre-existing invariant that the streaming path never polls
under normal operation. When it does fire, it fetches a bounded number of
the most recent REST candles (`gap_fill_lookback_bars`, default 20) and
publishes only the ones that are both newer than the last bar already
observed/backfilled and strictly older than the current live bucket --
i.e. only genuinely CLOSED bars, marked `LiveCandle.gap_filled=True` for
provenance. It never fabricates individual missed trades or attempts to
reconstruct intra-bar activity. A high-water mark per `(symbol,
timeframe)` prevents republishing the same backfilled bars on a second
reconnect soon after the first.

## WS frame schema_version

Every outbound `/api/live/stream` frame is now wrapped with
`{"schema_version": 1, ...}` at the single choke point where frames leave
the connection (`_send_frame` in `app.api.routes.live`), so a future
breaking change to an existing frame TYPE's shape can be detected by
consumers instead of silently misparsed. Adding a brand-new frame `type`
does not require a version bump; changing an existing type's fields does.

## Multi-timeframe aggregation: already correct, no rewrite needed

Investigation found `LiveMarketService` already folds every symbol's
subscribed timeframes independently from the same underlying tick/
aggregate stream (`_fold_forming_candle`/`_fold_forming_candle_from_aggregate`
loop over `state.timeframes`), each using its own `bucket_start()`-derived
bucket and its own independent volume accumulator -- there is no
"derive 5m from already-closed 1m bars" step, and so no risk of double-
counting volume across timeframes. This phase added explicit test
coverage for the previously-unverified claim rather than any new
production code.

## Dev-only mock live simulator: real pipeline, never real research

`/api/dev/live-simulator` (backend) and `/dev/live-simulator` (frontend)
let a developer hand-script `app.live.mock_streaming.MockStreamingProvider`
-- push a trade, simulate a disconnect -- to preview forming-candle/
reconnect/gap-fill UX without any real provider account. Both are
unreachable unless `ENABLE_DEV_LIVE_SIMULATOR=true`, which the production
config validator (`Settings._validate_production_safety`) makes a hard
startup failure to set alongside `ENVIRONMENT=production` -- not
discouraged, structurally impossible. The frontend page additionally
404s via a server-component guard (`process.env.NODE_ENV === "production"`)
before any client bundle for it is even reachable.

When active, the simulator's events flow through the *exact same*
`LiveMarketService` → `RecomputationEngine` → Decision Engine pipeline
real market data does -- deliberately, since that's what makes the UX
preview realistic. This creates a genuine research-integrity risk: a
decision plan built from synthetic mock data is otherwise
indistinguishable from a real one (real, non-fixture `setup_id`, a real
persisted `DecisionPlan`). The fix is process-wide, not per-event:
`app.alerts.prospective.is_prospective_eligible` now returns `False`
unconditionally whenever `settings.enable_dev_live_simulator` is true,
checked fresh on every call. Combined with the existing Phase 14.1
provenance checks (fixture symbols, `fixture:`-prefixed setup IDs), this
means nothing this process observes while the simulator is enabled can
ever feed Forward Validation.

## Provider secrets

Unchanged principle from Phase 12.2, reconfirmed end-to-end this phase:
`massive_api_key` is read only by backend provider-construction code
(`app.api.deps`), never returned by any route. `MarketDataEntitlement.reason`
is a fixed, human-readable sentence -- it never embeds the key value
itself. Verified by an integration test that configures a realistic fake
secret and asserts it never appears in `/api/live/status` or
`/api/dev/live-simulator/status` response bodies.

## What was explicitly NOT built

- No brokerage execution, no automatic trading, no BUY/SELL/probability
  scoring -- out of scope by the phase's own binding constraints.
- No cross-process/Redis event bus -- the app remains single-process per
  Phase 16's worker/api split; multi-instance streaming ownership was not
  a genuine deployment need this phase.
- No purchase of, or upgrade to, any provider account. This environment's
  Massive configuration was checked and found NOT entitled (no API key
  configured at all) -- see the Phase 17 final report for the explicit
  entitled/not-entitled/unknown determination.

## Activation checklist (for an eligible contracting party, later)

See `docs/deployment.md` "Activating a licensed real-time provider" for
the concrete steps once a parent/guardian, adult business entity, or the
product owner (once legally eligible) has an actual licensed Massive
account: setting `MASSIVE_API_KEY` and, only after confirming the
account's real plan tier, `MASSIVE_STREAMING_ENTITLED=true`. No code
change is required for that activation -- this ADR's entire point.
