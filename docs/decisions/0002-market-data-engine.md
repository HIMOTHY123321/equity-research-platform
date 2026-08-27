# ADR 0002: Market data engine (Phase 2)

## Provider abstraction

`app/market_data/provider.py` defines `MarketDataProvider` as an ABC with
three methods: `get_candles`, `get_latest_quote`, `get_previous_close`.
`AlpacaMarketDataProvider` is the only implementation, and it's the only
module that imports `httpx` or knows Alpaca's URL shapes. Routes and the
cache decorator depend only on the abstract interface, and tests inject
either a fake `MarketDataProvider` or a real `AlpacaMarketDataProvider` with
an `httpx.MockTransport` — none of the 86 backend tests touch the network.

## Session-aware 4H aggregation

Alpaca has no native 4-hour timeframe. The naive approach — group every four
1H bars — silently merges bars across trading-day boundaries and across
holiday-shortened sessions, producing a 4H candle that mixes two unrelated
sessions with no way to tell from the output. `app/market_data/aggregation.py`
instead:

1. Drops pre-market/after-hours bars entirely — 4H structure is regular-session structure.
2. Groups the remaining bars by exchange trading date (`America/New_York`), so a bucket can never span two calendar days.
3. Within a single day, buckets by elapsed time since the regular session open (09:30 ET), not by bar count — `floor(elapsed_seconds / 4h)`.

For a full 6.5-hour regular session this naturally produces two buckets per
day (09:30-13:30 and 13:30-16:00, the second shorter since the session ends
before a full 4 hours). A holiday-shortened session just produces fewer bars
in bucket zero and no bucket one — no special-casing needed, and nothing is
fabricated to fill the gap. See `tests/unit/market_data/test_aggregation.py`
for the boundary cases this is tested against (short session not merging
into the next day, extended-hours bars excluded, two trading days never
sharing a bucket).

## Session classification

`app/market_data/sessions.py` classifies any timestamp as `pre_market`
(04:00-09:30 ET), `regular` (09:30-16:00 ET), or `after_hours` (16:00-20:00
ET) — the standard NYSE/Nasdaq extended-hours convention. This is not a full
holiday calendar; Alpaca simply returns no bars for closed days and we never
fabricate bars to fill that gap. `session` is now a field on `Candle` itself
(`app/schemas/market_data.py`), defaulting to `regular` so Phase 1's tests
stay valid unchanged.

## Malformed data is never silently dropped

`app/market_data/normalization.py` returns a `NormalizationResult` with
`candles`, `rejected` (each with the raw bar and a reason), and
`duplicates_dropped`. `AlpacaMarketDataProvider` logs a warning for every
rejection and every dropped duplicate — bad bars are visible, not swallowed.
Deduplication keeps the first occurrence of a timestamp; ordering is always
enforced by sorting ascending regardless of what order the provider returned
bars in.

## Retries, rate limits, auth

`AlpacaMarketDataProvider._request` retries on connection errors and 5xx
with exponential backoff, and retries on 429 respecting the `Retry-After`
header when present. 401/403 raise `AuthenticationError` immediately with no
retry — a retry can't fix a bad key. All of this is driven by an injectable
`sleep_fn`, so retry tests run in milliseconds with no real waiting.

## Caching

`CachedMarketDataProvider` wraps any `MarketDataProvider` with a `Cache`
(`InMemoryCache` for now) behind the same interface, so routes don't know
caching exists. TTLs differ by data volatility: 30s for candles, 5s for
quotes, 1h for previous close.

## Watchlist without a database

`app/watchlist/repository.py` defines `WatchlistRepository` with an
`InMemoryWatchlistRepository` default, seeded with SPY/QQQ/NVDA/AAPL/
MSFT/META/AMZN/TSLA. A SQLAlchemy-backed implementation against the
`watchlists`/`watchlist_symbols` tables (already defined in Phase 1's
`app/database/models.py`) can replace it once `DATABASE_URL` is reachable —
routes only depend on the interface via `app/api/deps.py`.

## Python 3.9 follow-through

Same constraint as ADR 0001: pydantic v2 also fails to evaluate `X | None`
annotations at runtime on 3.9 (confirmed empirically — see commit history),
not just SQLAlchemy. `app/schemas/responses.py` uses `typing.Optional`
accordingly. `zoneinfo` (stdlib since 3.9) is used for exchange-timezone
math; `tzdata` is pinned as an explicit dependency so this doesn't silently
depend on the host OS having an IANA timezone database installed.
