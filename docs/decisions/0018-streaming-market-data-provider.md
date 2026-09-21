# ADR 0018: Streaming Market Data Provider (Phase 12.2)

## Motivation

Phase 12.1 (ADR 0017) built the automatic live-data architecture but was
honest that its only real provider, yfinance, has no push/streaming API at
all — every "live" update was a poll, floored at `min_poll_interval_seconds
=3.0`. Phase 12.2 replaces the primary live-market path with a real
push-based feed (Massive, massive.com) while preserving yfinance as the
zero-credential development/test fallback, and extends the Phase 12.1
architecture rather than building a second one alongside it.

**RANKING GATE remains FAIL (ADR 0012), untouched. Phase 13 was not
started.** Nothing here adds a recommendation, probability, or ranking
score — it only delivers the same deterministic data faster and with a real
source timestamp.

## Provider selected: Massive

Massive's stocks WebSocket API (`massive.com/docs/websocket/stocks/*`,
verified against current official docs during this phase) genuinely pushes:
trades (`T.<SYM>`), NBBO quotes (`Q.<SYM>`), and per-second OHLCV aggregates
(`A.<SYM>`) over one persistent connection that can subscribe to many
tickers/channels at once. Its wire schema is Polygon.io-family-compatible
(`ev/sym/p/s/t/q/...`), which is why `app.market_data.massive_streaming`'s
module docstring calls this out explicitly — nothing about that schema is
assumed to be exclusive to Massive, and it is exactly the kind of detail
that could change with a future provider swap.

**Entitlement**: real-time (non-15-min-delayed) streaming requires the
"Advanced" tier ($199/mo) or above. This development environment has no
Massive account/API key, so the real streaming path (`Massive
StreamingProvider`) is built and unit-tested against a fully scripted fake
WebSocket transport (`tests/unit/market_data/test_massive_streaming.py`),
never a real socket, and the 10-minute live acceptance test from the
original spec (§Z) was **not run** — reported honestly below rather than
fabricated.

## Extending, not replacing, Phase 12.1

Before writing any code, the existing `app/live/` architecture was
re-inspected end to end (`LiveMarketService`, `RecomputationEngine`,
`ForecastMonitor`, `NewsMonitor`, `/api/live/stream`, `liveClient.ts`,
`useLiveSymbol`) and found to already provide almost everything Phase 12.2
needed structurally:

- **Bar-close reconciliation already existed.** `RecomputationEngine`
  reacts only to `CompletedCandleEvent` and re-fetches the authoritative bar
  via a fresh `market_provider.get_candles()` REST call — it never trusts
  the live-folded OHLC, streaming or polled. Phase 12.2 therefore did not
  need to build a separate "confirm against provider" step; it only needed
  to keep firing `CompletedCandleEvent` at the same real bar boundary,
  which `app.live.candle_builder.bucket_start` already computes correctly
  regardless of what fed the forming candle.
- **The event bus, WebSocket transport, freshness states, and forming/
  completed candle separation (§G) all carry over unchanged.**

What Phase 12.2 actually added is a second, parallel path inside
`LiveMarketService`:

```
Massive WebSocket
        v
MassiveStreamingProvider (app/market_data/massive_streaming.py)
        v
LiveMarketService._stream_supervisor  <-- ONE task, ONE connection, all symbols
        v
ingest_trade / ingest_nbbo / ingest_second_aggregate
        v
existing event bus (QuoteEvent/FormingCandleEvent/CompletedCandleEvent)
        v
existing /api/live/stream -> existing liveClient.ts -> existing useLiveSymbol
```

`LiveMarketService.subscribe()`/`unsubscribe()` now branch on `_use_streaming()`
(true only when a `StreamingMarketDataProvider` is configured **and** its
`capabilities()` genuinely declare `streaming_trades`/`streaming_quotes`):
streaming symbols register against the one shared `_stream_supervisor` task;
everything else falls through to Phase 12.1's unchanged per-symbol poll
loop. yfinance/Alpaca never see this new path at all.

## Provider capability design

`ProviderCapabilities` (Phase 12.1) already existed as the single source of
truth for streaming-vs-polling and cadence claims; Phase 12.2 just adds
`MASSIVE_CAPABILITIES` (`app/market_data/capabilities.py`) with
`streaming_quotes=streaming_trades=streaming_bars=True` — the first
genuinely-true streaming claim in this codebase. `quote_delay_seconds`
stays `None` on principle: Massive's own SIP timestamp lets `app.live.
latency.LatencyTracker` **measure** transport latency per message, which is
more honest than repeating a vendor-stated number this codebase hasn't
independently verified.

A second, provider-agnostic abstraction was added alongside it:
`StreamingMarketDataProvider` (`app/live/streaming.py`) — `connect`/
`disconnect`/`subscribe`/`unsubscribe`/`events()`, normalized
`StreamTrade`/`StreamNbbo`/`StreamAggregate`/`StreamStatus` event types. No
Massive-shaped field name (`sym`, `bp`, `ap`, `ev`) crosses this boundary; a
future licensed provider (a real Alpaca streaming feed, IEX, etc.)
implements this same interface with zero changes above it — the same
swap-without-ripple discipline `MarketDataProvider` already established for
historical data in Phase 6.

`MockStreamingProvider` (`app/live/mock_streaming.py`) is the only
streaming provider any test in this codebase talks to — fully scriptable
(`push_event`/`push_disconnect`), used for every ordering/reconnect/
forming-candle test in `tests/unit/live/test_streaming_service.py`.

## Normalized event schemas

```python
StreamTrade(symbol, price, size, exchange, conditions, source_timestamp, sequence)
StreamNbbo(symbol, bid, ask, bid_size, ask_size, source_timestamp, sequence)
StreamAggregate(symbol, open, high, low, close, volume, window_start, window_end)
StreamStatus(connected, message)
```

`app.market_data.massive_streaming._normalize_message` is the one place
that ever sees Massive's raw `{"ev": "T", "sym": ..., "p": ..., "t": ...}`
shape; every required field is validated (`KeyError`/`TypeError`/
`ValueError` caught) and a malformed message is logged and dropped, never
raised past this boundary (§V — untrusted external input).

## Trade vs. quote semantics (§G)

`LiveQuote` (Phase 12.1) gained additive, optional fields: `last_trade_price
/size/timestamp/exchange` and `nbbo_timestamp`. `price` is now the real
last-trade price once any trade has been observed for a symbol — `ingest_
trade` sets it directly from `StreamTrade.price`, never a midpoint.
`ingest_nbbo` updates `bid`/`ask`/`spread`/`nbbo_timestamp` independently
and only falls back to an approximate `(bid+ask)/2` for `price` when no real
trade has been seen yet (the same honest-degradation pattern the yfinance
path already used, `is_approximate=True` in that case only). A trade and
its NBBO genuinely carry different source timestamps — both are preserved
and both are shown separately in `LiveQuoteHeader.tsx` ("Last trade: ..." /
"NBBO: bid / ask @ ...") rather than collapsed into one generic freshness
clock.

## Ordering, dedup, and out-of-order handling (§E/§M)

`app.live.service._is_newer(timestamp, sequence, last_timestamp,
last_sequence)` is the one ordering policy, shared by `ingest_trade` and
`ingest_nbbo`: a strictly later `source_timestamp` is always accepted; an
equal timestamp is only accepted if both sides carry a sequence number and
the new one is strictly greater; anything else (older timestamp, equal
timestamp with no usable sequence, a reconnect replay) is dropped. Older
state never overwrites newer state — proven directly in
`test_streaming_service.py` (`test_an_older_trade_never_overwrites_a_newer_
one`, `test_same_timestamp_trade_uses_sequence_as_tiebreak`, `test_stale_
aggregate_replay_is_dropped`). Per-second aggregates use a simpler
`window_end`-only guard (no natural sequence field in that channel) — a
replayed/duplicate window is dropped by timestamp alone.

## Forming candles from real aggregates (§H)

`app.live.candle_builder.fold_aggregate_into_candle` folds a real
per-second OHLCV window into the forming bar for its bucket — genuine
volume accumulation, replacing the Phase 12.1 quote-driven fold's
`volume=0.0` approximation. `LiveMarketService._fold_forming_candle_from_
aggregate` reuses the exact same boundary-crossing logic Phase 12.1's
quote-driven fold already used: a bucket change publishes `CompletedCandle
Event` for the old bar before starting a new one. A 1-second aggregate is
never itself promoted into a confirmed 5m/15m/1h/4h/1D research bar — only
the real timeframe boundary crossing does that, and (as noted above)
`RecomputationEngine` re-derives the authoritative bar via REST regardless
of what the live fold showed, so no intrabar high/low can become permanent
if provider reconciliation would disagree.

## Reconnect / resync (§P/§Q)

`LiveMarketService._stream_supervisor` is the **one** task owning the
upstream connection for every subscribed symbol. On any failure raised out
of `provider.events()`: `CONNECTED` -> `DISCONNECTED` immediately, exponential
backoff (reusing `LiveConfig`'s existing `reconnect_initial/max_backoff_
seconds`/`reconnect_backoff_multiplier` — the same fields Phase 12.1's poll
loop already used), then `RESYNCING`, then `connect()` + re-authenticate +
resubscribe every symbol/channel still tracked in `self._symbols`, and only
a successful post-resubscribe event brings the state back to `CONNECTED`.
Proven directly: `test_disconnect_then_reconnect_resubscribes_every_
tracked_symbol` simulates a drop via `MockStreamingProvider.push_disconnect()`
and asserts both symbols are back in `provider.subscriptions` after
recovery, with `reconnect_attempts` reset to 0.

**Not implemented in this phase**: automatic fallback from a disconnected
Massive stream to yfinance polling mid-session. The original spec listed
this as OPTIONAL. A disconnected/resyncing Massive stream stays honestly
`DISCONNECTED`/`RESYNCING` in the UI rather than silently blending two
providers' data with no indication of provenance (§P: "do not silently mix
providers without provenance") — a defensible, explicitly documented scope
cut rather than a partial, risk-prone implementation.

## Latency measurement (§N)

`app.live.latency.LatencyTracker` records `received_at - source_timestamp`
per `(event_type, symbol, provider)`, bounded to the newest 500 samples per
key (never unbounded growth), and reports median/p95/p99/max. Wired into
`ingest_trade`/`ingest_nbbo`/`ingest_second_aggregate` and surfaced at
`GET /api/live/status` under `"latency"`. This is what makes any future
latency claim about Massive an observed number, not an assumption that
WebSocket transport implies low latency.

## Security (§V)

`MASSIVE_API_KEY` is read only from `app.config.Settings` (server-side
environment) and only ever sent once, over TLS, as the WebSocket auth
message's own payload (`{"action":"auth","params":"<key>"}`) — never logged,
never in an exception message, never reachable from the browser (the
browser only ever talks to this backend's own `/api/live/stream`). Every
inbound message is schema-validated before use; a malformed or unrecognized
event is dropped and logged, never crashes the stream or is forwarded
upward. Oversized messages (>1MB) are dropped without parsing.

## Fallback behavior (§C/§AA)

`app.api.deps.get_streaming_provider()` returns `None` whenever `MARKET_
DATA_PROVIDER != "massive"` or `MASSIVE_API_KEY` is unset — no exception,
no degraded startup. `LiveMarketService` with `streaming_provider=None`
behaves byte-for-byte as Phase 12.1 did: per-symbol poll loop, yfinance
labeling, `is_streaming() == False`. No test in this codebase, and no app
startup path, requires a Massive credential.

## SPCX and newly-listed symbols (§S/§T)

Not independently verified against a live Massive feed in this session (no
account/key available) — reported honestly rather than assumed. The
architecture places no special case anywhere for any specific ticker
(§S "do not hardcode SPCX behavior" is respected by construction: `Massive
MarketDataProvider`/`MassiveStreamingProvider` take a plain `symbol: str`
throughout). A newly-listed symbol with live Massive trade/quote data but
insufficient historical bars continues to hit Phase 12's existing
`INSUFFICIENT_HISTORY`/abstain path unchanged — live-feed availability was
already decoupled from research-quality gating before this phase and
nothing here changes that boundary.

## Licensing / commercial boundary (§AC)

Development in this repository used no Massive account (no key available).
Real-time streaming access requires Massive's "Advanced" tier or above; the
"Business" tier (or a negotiated agreement) is required for commercial/
display/redistribution rights beyond a single application's own internal
use — an individual developer's API key does not, by itself, grant
redistribution rights for a commercial SaaS product. This codebase never
persists Massive's raw firehose (§W: no full-feed logging by default,
sampled/aggregate diagnostics only if explicitly enabled) and treats every
inbound message as licensed data to be displayed within this application,
not redistributed.

## Known limitations

- No live 10-minute Massive acceptance test was run (§Z) — no credential
  available in this environment. The streaming path is proven by unit tests
  against a fully scripted fake WebSocket transport and by the
  `MockStreamingProvider`-driven `LiveMarketService` suite, not by an
  observed real feed.
- No automatic Massive-down -> yfinance-up mid-session failover (explicitly
  optional per spec, cut for this phase — see "Reconnect / resync" above).
- The event bus remains a single-process, in-memory `asyncio.Queue` fan-out
  (unchanged from Phase 12.1) — this does not scale past one backend worker
  process without a shared broker (Redis pub/sub or similar); out of scope
  here, same limitation ADR 0017 already noted.
- `MassiveMarketDataProvider`'s REST endpoints (`/v3/quotes`, `/v2/aggs/...`)
  were implemented against current official documentation but not
  exercised against the real API (no key) — only against a mocked HTTP
  transport (`tests/unit/market_data/test_massive_provider.py`).
