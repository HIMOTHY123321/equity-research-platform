# ADR 0006: yfinance as the development/research market-data provider

## Why not Alpaca

Alpaca was the original target provider (ADR 0002). It was replaced before
any live Alpaca connection was made: the account holder is underage and will
not create or use an Alpaca account, since doing so would violate Alpaca's
account eligibility requirements. This is a firm constraint, not a
technical one — `AlpacaMarketDataProvider` is **not deleted**. It remains
fully implemented and isolated in `app/market_data/alpaca_provider.py` so an
eligible account holder (or a later commercial/licensed data deal) can
switch back by changing one config value, never by editing call sites.

## Provider selection: config only, never hard-coded

`app/config.py` adds `market_data_provider: str = "yfinance"`.
`app/api/deps.py::_build_inner_provider()` is the **only** place a concrete
provider class is constructed:

```python
def _build_inner_provider() -> MarketDataProvider:
    provider_name = get_settings().market_data_provider.lower()
    if provider_name == "alpaca":
        return AlpacaMarketDataProvider()
    if provider_name == "yfinance":
        return YFinanceMarketDataProvider()
    raise ValueError(...)
```

Nothing else in the codebase imports a concrete provider. Both providers
still pass through the same `CachedMarketDataProvider` wrapper, so caching
behavior (30s candles / 5s quotes / 1hr previous-close TTLs) is identical
regardless of which provider is active.

## What changed vs. what didn't

- **Unchanged**: `MarketDataProvider` abstract interface, the normalized
  `Candle`/`Quote`/`PreviousClose` schemas, the session-aware 4H-from-1H
  aggregation logic (`aggregation.py` — zero code changes, hand-verified
  byte-exact against live yfinance 1H bars), the feature/structure/S&R
  engines (provider-agnostic by design from Phase 2 onward).
- **New**: `YFinanceMarketDataProvider`, `normalize_yfinance_bar(s)` in
  `normalization.py`, `Quote.is_approximate` (see below).

## Honest limitations (this is a research/dev feed, not institutional data)

- **No real bid/ask.** `get_latest_quote` returns the last trade price as
  both bid and ask (`bid_size`/`ask_size` = 0) and sets
  `Quote.is_approximate = True` explicitly, so downstream consumers — and a
  future AI layer — can never mistake this for a real NBBO quote. Always
  `False` for providers with a genuine quote feed.
- **Extended-hours volume is always 0.** Empirically confirmed against real
  pre-market/after-hours bars for all 8 test symbols — this is what Yahoo's
  free intraday feed actually returns, not a normalization bug. `Candle`
  allows `volume == 0`.
- **Intraday history window is short and Yahoo-imposed, not ours to
  extend.** Empirically verified against live data:

  | Timeframe | Yahoo's real limit | Our request |
  |---|---|---|
  | 1d | effectively unlimited | 300 bars (~14 months) |
  | 1h | ~730 calendar days | 2000 bars (~120 trading days) |
  | 15m | ~60 calendar days | max available (~3.7k bars) |
  | 5m | ~60 calendar days | max available (~11k bars) |

  `get_candles` always requests the real maximum period for the timeframe
  and trims to `limit` — it never silently returns less than what's
  available, and never fabricates bars beyond what Yahoo has.
- **Rate limiting is real and unauthenticated.** `yfinance` has no API key,
  so there is no SLA. `_history`/`_fast_info_price` retry with capped
  exponential backoff (`0.5s, 1s, ..., capped at 4s`) on
  `YFRateLimitError`, then raise `RateLimitError` — never silently return
  stale or partial data.

## Real-data validation checkpoint (2026-08, SPY/QQQ/NVDA/AAPL/MSFT/META/AMZN/TSLA)

Performed in place of the originally-planned Alpaca checkpoint (ADR 0002),
after replacing the provider. Summary of findings (full report delivered in
conversation, not duplicated here):

- All 40 symbol × timeframe candle fetches (8 symbols × 5 timeframes)
  returned valid, correctly-normalized real data.
- 4H aggregation from real 1H bars verified byte-exact by hand.
- Feature engine values (ATR14, EMA20/SMA50/SMA200, RVOL, previous
  day/week) hand-verified arithmetically correct against real SPY/QQQ/NVDA
  data.
- **Bug found and fixed via real data**: `classify_trend`'s original
  zero-contradiction rule misclassified every real bullish
  SPY/QQQ/NVDA daily/1H case as `ranging` — see ADR 0004's addendum.
- Anti-lookahead invariant (`pivot_timestamp < confirmed_at`, S/R
  `known_at` gating) spot-checked against a real NVDA swing — passes.
- Support/resistance zone confluence, lifecycle, and nearest-zone selection
  spot-checked against real SPY/QQQ/NVDA zones — correct, including the
  "zone containing current price is excluded from `nearest_support`/
  `nearest_resistance`" edge case, which is deliberate design
  (`app/support_resistance/nearest.py`), not a bug.
- Caching confirmed effective (candle fetch: ~660ms cold → ~1.5ms warm).
  `/structure` and `/levels` recompute their snapshots on every call (no
  snapshot-level cache, only candle-level) — acceptable at current scale
  (~30-50ms warm-candle recompute cost for a single-user research tool),
  flagged as a future optimization if request volume grows.

## Should this project upgrade to a licensed provider before public release?

**Yes, before any public/multi-user release** — not because yfinance's
*data quality* was found to be wrong (it wasn't; every value checked was
arithmetically correct), but because of what it structurally cannot
provide:

1. No SLA or authenticated rate limits — unsuitable for anything beyond a
   single developer's research use.
2. No real bid/ask — any feature that needs genuine spread/liquidity data
   (execution modeling, realistic paper-trading fills) cannot be built on
   this feed honestly.
3. Terms-of-service posture — `yfinance` scrapes a public endpoint Yahoo
   does not officially support for commercial redistribution; fine for
   personal research and development, not something to build a product on.
4. Short intraday history (~60 days for 5m/15m) caps how much intraday
   backtesting history is ever available.

For continued solo development and paper-trading research, yfinance remains
appropriate and honestly labeled as such (`is_approximate`, dev-only
docstrings, no institutional-grade claims anywhere in the code or UI). The
provider abstraction means this upgrade is a config change plus one new
`MarketDataProvider` implementation whenever it's warranted — not a
rearchitecture.
