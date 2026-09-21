# ADR 0017: Automatic Live Data & Event-Driven Updates (Phase 12.1)

## Motivation

Every prior phase required the user to act: open a ticker, click a button,
reload a page. Phase 12.1's product requirement is that AI Market Desk
**updates itself** — the user should never need to refresh the browser,
press a button, or ask again to see current market data, an auto-resolved
forecast, or fresh news. This phase adds the automatic live-data
infrastructure underneath the whole product, without weakening any
deterministic/no-lookahead guarantee established in Phases 1–12.

**RANKING GATE remains FAIL (ADR 0012), untouched.** Nothing here computes
a score, a recommendation, or a probability faster; it only delivers
already-existing deterministic data (quotes, candles, forecasts, catalysts)
to the browser without a manual refresh.

## 1-second target, and why it is not what actually happens

The product target is a 1-second update cadence. The honest reality,
verified directly against the real yfinance dev provider: **yfinance has no
push/streaming API of any kind.** `YFinanceMarketDataProvider.get_latest_
quote` (`app/market_data/yfinance_provider.py`) makes one blocking HTTP
call per invocation, already defensively rate-limit-guarded (`YFRateLimit
Error` retry/backoff). Polling it every second, for every subscriber, would
risk exactly the rate-limiting that guard exists to prevent.

`ProviderCapabilities` (`app/market_data/capabilities.py`) makes this
explicit rather than silently approximating it: `streaming_quotes=False`,
`real_time_quotes=False`, `quote_delay_seconds=None` (not "0" — Yahoo
publishes no latency SLA, so an unmeasured delay is recorded as unmeasured,
never assumed to be zero), and `min_poll_interval_seconds=3.0` — a
conservative floor derived from, not lower than, yfinance's existing
retry/backoff tuning. `app.live.config.resolve_poll_interval` is the one
function that turns "1 second is the target" into "here is what can
actually, truthfully be delivered": `max(provider_floor, target) ×
priority_multiplier`. The target is real; the provider is the limiting
factor, not this codebase's polling discipline.

## Streaming vs. polling decision

**Polling, behind a streaming-shaped interface, documented honestly here
rather than hidden.** `LiveMarketService.subscribe`/`unsubscribe`/`add_
listener` and the WebSocket transport are exactly what a genuinely
streaming provider would need — a future licensed real-time feed
implements `MarketDataProvider.capabilities()` truthfully (`streaming_
quotes=True`, a measured `quote_delay_seconds`) and `LiveMarketService`'s
poll loop becomes a push-subscription loop with **zero changes** to the
WebSocket contract, the frontend, or any route. This is the actual
migration path (see "Commercial provider migration path" below), not a
hypothetical.

Client↔server transport is **WebSocket**, not SSE: the protocol is
genuinely bidirectional (the client sends `subscribe`/`unsubscribe`
messages, not just receives a stream), and `uvicorn[standard]` (already a
dependency) provides native FastAPI WebSocket support with zero new
packages. SSE was considered and rejected only because it's one-directional
by design — nothing about this decision reflects a belief that SSE is
generally worse.

## Provider capability abstraction

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    real_time_quotes: bool
    streaming_quotes: bool
    streaming_trades: bool
    streaming_bars: bool
    streaming_news: bool
    historical_intraday: bool
    quote_delay_seconds: Optional[float]   # None = unmeasured, never assumed 0
    news_delay_seconds: Optional[float]
    min_poll_interval_seconds: float
```

`MarketDataProvider.capabilities()` is a **concrete method with a
conservative "capabilities unknown" default** on the ABC, not abstract —
making it abstract would have forced all 17 test-only fake provider
subclasses across the existing suite to implement it for no benefit; the
default (`streaming_quotes=False`, `quote_delay_seconds=None`, a 5s poll
floor) is safe for anything that doesn't override it. `YFinanceMarketData
Provider` and `AlpacaMarketDataProvider` (this implementation only makes
plain REST calls via `httpx`, even though Alpaca's platform genuinely
offers a real streaming feed for paying accounts — the capability describes
what *this implementation* does, never what the vendor is theoretically
capable of) each declare their own real, verified values.
`CachedMarketDataProvider` passes the inner provider's capabilities through
unchanged.

## 1-second scheduling strategy

One `asyncio` poll loop per **subscribed symbol** (`LiveMarketService.
_poll_loop`), not per component and not per WebSocket connection — N
browser tabs watching SPY share exactly one upstream loop
(`_tasks: dict[str, asyncio.Task]`, refcounted subscribe/unsubscribe).
Each iteration calls the (blocking) `get_latest_quote` via `asyncio.
to_thread` so it never blocks the event loop, then sleeps for
`resolve_poll_interval(capabilities.min_poll_interval_seconds, priority)`.

Priority tiers (`SubscriptionPriority`: `VIEWED` → `ACTIVE_FORECAST` →
`WATCHLIST` → `BACKGROUND_BENCHMARK`) scale the interval up for
lower-priority symbols so a large watchlist can never starve the ticker
the user is actually looking at, or trip the provider's real rate limit.
`_highest_priority` recomputes the effective tier every iteration from the
current subscriber set, so a symbol that's both watchlisted and currently
viewed always polls at the viewed-tier cadence.

## Forming vs. completed candles — the load-bearing invariant

A forming candle (`app.live.candle_builder.fold_price_into_candle`) is
folded from live quotes **only in `LiveMarketService`'s in-memory state**
(`_SymbolState.forming_candles`). It is never written to the candle
cache/DB, and never passed to `build_market_snapshot`/`get_candles`. Bucket
alignment reuses the exact session-open-relative convention `app.market_
data.aggregation` already established for 4H bars (never a second,
diverging alignment rule), so a forming bar reconciles with whatever
`get_candles()` authoritatively reports once it actually closes.

The forming→completed transition is a pure wall-clock boundary crossing
(`app.live.candle_builder.bucket_start`, cross-checked against `app.market_
structure.common.candle_complete_at` — the same authority every historical
engine already uses). Only that transition emits a `CompletedCandleEvent`;
a quote tick or a forming-candle price move never does. This is what
mechanically — not by convention — prevents premature pivot/BOS/CHOCH/
setup confirmation: those engines only ever see whatever `get_candles()`
returns, and a forming candle is never in that return value. Proven
directly, not just asserted: `tests/unit/live/test_recompute.py`'s `test_
quote_event_never_triggers_recomputation`/`test_forming_candle_event_
never_triggers_recomputation` assert `RecomputationEngine.handle_event`
returns `None` (no recompute happened at all) for those event types.

## Event-driven recomputation graph

```
QUOTE / forming candle  ->  update UI only, RecomputationEngine untouched
COMPLETED CANDLE        ->  cache.delete_prefix("candles:{symbol}:{tf}:")
                         ->  build_market_snapshot(...) [[reused verbatim]]
                         ->  cached snapshot available for the next read/push
FORECAST HORIZON CLOSED ->  ForecastMonitor.scan_and_resolve_once
                         ->  resolve_forecast (unchanged, Phase 12)
NEW ARTICLE              ->  NewsMonitor.scan_once
                         ->  ingest -> classify -> group -> catalyst refresh
                         ->  NewEvidenceEvent (never regenerates a brief)
```

`RecomputationEngine.handle_event` is the one function that decides
whether an event is actionable — `isinstance(event, CompletedCandleEvent)`
is the entire gate. A completed-candle event also calls `Cache.
delete_prefix` (a small, additive method added to the `Cache` ABC/`InMemory
Cache` this phase) to force the next `get_candles()` call to see the
newly-closed bar immediately, rather than waiting out whatever TTL happened
to be mid-flight.

## Background forecast monitoring (page-independent)

`ForecastMonitor` is a plain `asyncio.create_task`, started once in `app.
main`'s `lifespan`, with **no dependency on any HTTP request or React page
whatsoever** — proven directly, not just designed that way: every test in
`tests/unit/live/test_forecast_monitor.py` calls `scan_and_resolve_once()`
with no FastAPI app, no HTTP client, no browser page in the picture at all,
which is itself the proof that resolution doesn't depend on a page being
open. It periodically lists `ACTIVE` prospective forecasts and calls the
existing, completely unmodified `resolve_forecast` (Phase 12) — this module
adds scheduling, never a second resolution implementation. The original
`ForwardForecast` stays exactly as immutable as Phase 12 already made it.

### A real bug found and fixed during this phase

The Phase 12 `POST /{forecast_id}/resolve` route always persisted whatever
`resolve_forecast` returned, including `INSUFFICIENT_FUTURE_DATA`. Because
`save_outcome` is idempotent on first write (the mechanical enforcement
behind "a forecast can only ever have one outcome"), persisting a too-early
"not enough data yet" attempt would have **permanently locked that forecast
out of ever resolving**, even once its horizon genuinely closed later. This
was latent but harmless in Phase 12 (nothing called resolve automatically,
so a user only hit it by clicking RESOLVE before the horizon closed and
then never re-clicking). Phase 12.1's background monitor calls resolve
*constantly* — this bug would have made automatic resolution effectively
never work. Fixed in both the manual route and `ForecastMonitor.scan_and_
resolve_once`: an `INSUFFICIENT_FUTURE_DATA` result is never persisted; the
forecast simply stays `ACTIVE` and is retried on the next scan/click. See
`test_an_insufficient_future_data_resolution_is_never_persisted_
permanently` and `test_insufficient_future_data_is_never_persisted_and_
remains_rescannable`.

## News/catalyst auto-refresh

`NewsMonitor` reuses the exact ingestion pipeline `GET /api/news/{symbol}`/
`GET /api/catalysts/{symbol}` already run per-request (`provider.fetch_
symbol_news` → `repository.upsert_articles` → `repository.events_for_
symbol_as_of` → `repository.persist_events_snapshot`) on a timer, never a
second pipeline. "New evidence" detection is deliberately baseline-then-
diff: the *first* scan for a newly-subscribed symbol only establishes a
baseline of already-known article ids and emits nothing (a fresh
subscription must never be flooded with "new evidence" for articles that
were already there); only a *subsequent* scan finding an id outside that
baseline counts as genuinely new. This module never calls `app.ai_
analysis.brief` — an existing frozen `ResearchBrief` is never regenerated
automatically; `NewEvidenceEvent` only signals that a new EvidencePacket/
brief version *could* now be created, which stays an explicit user action.

## Freshness states and thresholds

```python
class FreshnessState(str, Enum):
    LIVE = "live"; RECENT = "recent"; DELAYED = "delayed"; STALE = "stale"
    DISCONNECTED = "disconnected"; UNAVAILABLE = "unavailable"
    MARKET_CLOSED = "market_closed"
```

`classify_freshness` (`app/live/config.py`) is the **one** deterministic
classifier every live object's `freshness_state` comes from — never an ad
hoc per-component judgment call. Precedence, in order: disconnected wins
over everything; `MARKET_CLOSED` wins over a merely-fresh-looking
timestamp (a Friday-close quote can look numerically "fresh" without a
session check); then age-based thresholds (`live_max_age_seconds=5`,
`recent_max_age_seconds=30`, `delayed_max_age_seconds=120`, beyond that
`STALE`). `LiveSessionState` (`PRE_MARKET`/`REGULAR`/`AFTER_HOURS`/
`MARKET_CLOSED`) is a small, deliberately separate enum from `app.schemas.
market_data.MarketSession` — the latter classifies a historical *candle*
and has no "closed" concept (closed days simply have no candles); a live
dashboard genuinely needs to say "the market is closed right now," which
`app.live.market_hours.current_live_session` derives from `app.market_
data.sessions`' own boundary constants plus a weekday check (not a full
holiday calendar — the same documented limitation `app.market_data.
sessions` already carries).

For yfinance specifically: `age_seconds` reflects time since this value was
last confirmed by *this system's own poll*, not verified proximity to the
actual trade — Yahoo provides no trade-timestamp guarantee, so nothing here
claims tighter freshness than that. A future provider with a genuine
exchange-side timestamp makes the exact same `age_seconds` computation
automatically meaningful as true market latency, with no code change.

## Timestamps

`America/New_York` remains the one canonical display timezone
(`formatExchangeTimestamp`, unchanged from Phase 12), always to the second.
The chart's crosshair-hover readout (unchanged format from Phase 12) is
joined by a live forming-candle overlay (`CandlestickChart`'s new
`liveCandle` prop, applied via `lightweight-charts`' own `series.update()`
— purely visual, never written back into `candles`) and a forecast-marker
tooltip (ticker, forecast id, created/as-of/horizon/state) shown on hover.
Verified directly in-browser during this phase's validation, not just
asserted: DST is exercised across the EDT→EST transition boundary in
`tests/unit/live/test_config.py`.

## Connection health

`ConnectionState`: `CONNECTED` → `DISCONNECTED` → `RESYNCING` →
`CONNECTED`. `LiveMarketService` tracks its own connection to the
*provider* (poll success/failure); the WebSocket route separately tracks
the *browser's* connection to the backend (heartbeat frames every
`heartbeat_interval_seconds`, exponential backoff on the frontend's
`liveClient` for reconnect attempts, capped at 30s). On reconnect, the
frontend re-sends `subscribe` for every symbol it still holds a ref-count
for — the poll itself *is* the resync (a fresh `get_latest_quote` call), so
there's no separate "resync" data fetch needed beyond that.

### A second real bug found and fixed during this phase

`connection_status` events are only published on a **transition**
(`LiveMarketService._set_connection_state`), which is correct for existing
connections but means a *brand-new* WebSocket connection made while the
service was already `CONNECTED` from an earlier subscriber would never
receive any `connection_status` frame at all — the frontend's client-side
default (`DISCONNECTED`) would never be corrected, even though the backend
was genuinely live. Caught live, not just in a test: navigating to the
Forecast Lab page showed `DISCONNECTED` indefinitely despite `GET /api/
live/status` confirming the backend was `connected`. Fixed by having the
WebSocket route send an explicit connection-status snapshot immediately on
`accept()`, before waiting for any future transition. See `test_a_new_
connection_receives_the_current_connection_status_immediately`.

### A third real bug found and fixed during this phase

Every repository lazily calls `Base.metadata.create_all(..., checkfirst=
True)` on first instantiation — safe under one request at a time, but this
phase adds several always-on background threads (`RecomputationEngine`/
`ForecastMonitor`/`NewsMonitor`, each doing DB work via `asyncio.to_
thread`) that now routinely start at the same moment as a browser's first
request (itself thread-pooled by Starlette). On a brand-new SQLite file,
`checkfirst`'s own "inspect, then create if missing" is not atomic across
separate connections — two threads can both see a table as missing and
both issue `CREATE TABLE`, and the loser raises `sqlite3.OperationalError:
table ... already exists`. Observed live during this phase's own browser
validation (`news_articles`). Fixed by creating every table once,
synchronously, in `app.main`'s `lifespan` before any background thread
starts — by the time concurrency begins, there is no "missing table"
window left to race over. See `tests/unit/test_schema_concurrency.py`.

## Out-of-order / duplicate data

`LiveMarketService.ingest_quote` accepts a new quote only if its source
timestamp is **strictly newer** than the last accepted one; an equal
(duplicate) or older (delayed/out-of-order) timestamp is silently dropped
— "never allow an older update to overwrite newer state" is enforced by
one `<=` comparison, not a convention someone could forget to follow
elsewhere.

## Performance

No new caching layer beyond the existing `CachedMarketDataProvider`/
`InMemoryCache`. No brute-force per-second recomputation anywhere: quote/
forming-candle events are pure in-memory state updates and a WebSocket
push; the (expensive) `build_market_snapshot` call only ever runs on a
genuine completed-candle boundary. No AI/LLM invocation exists in this
phase's automatic path at all — `NewsMonitor` only ever signals "new
evidence available," it never calls `app.ai_analysis`.

## Commercial provider migration path

Swapping yfinance for a licensed streaming provider later requires no
rewrite of this phase's architecture: implement `MarketDataProvider` with
`capabilities()` returning `streaming_quotes=True` and a measured `quote_
delay_seconds`, and give `LiveMarketService._poll_loop` a streaming
variant that awaits the provider's own push events instead of sleeping
between polls (the subscribe/unsubscribe/event-bus contract is already
shaped for exactly this — no route, no frontend hook, no WebSocket message
shape needs to change). `ProviderCapabilities.min_poll_interval_seconds`
simply stops mattering once `streaming_quotes=True`.

## Limitations

- yfinance remains a development-only feed with no genuine sub-second (or
  even sub-multi-second) real-time guarantee; the UI never labels it
  otherwise (`(approximate)`, `via yfinance`, honest `freshness_state`
  everywhere a live value is shown).
- The in-memory event bus (`asyncio.Queue` per listener) is single-process
  only — running this multi-worker/multi-process in production would need
  the pub/sub layer moved to something like Redis. Deliberately not built
  now: this is a local, single-process backend, and adding that
  infrastructure without a present need would be exactly the kind of
  unjustified complexity this project's own conventions warn against.
- `_independent_episode_estimate`-style approximations elsewhere are
  unrelated to this phase and unchanged.
- No true automatic multi-hour forecast resolution was observed live
  during this phase's validation session (a real prospective forecast can
  only genuinely resolve once real wall-clock hours actually elapse) — the
  mechanism is proven by direct unit/integration tests
  (`ForecastMonitor`, the WebSocket forward path) rather than by watching
  it happen in real time within a single working session.
- Not a full market holiday calendar (unchanged, pre-existing limitation
  from `app.market_data.sessions`).

RANKING GATE remains **FAIL** (ADR 0012). Nothing in this phase computes a
score, rank, recommendation, or probability. Phase 13 is not started by
this work.
