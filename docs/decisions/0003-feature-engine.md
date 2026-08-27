# ADR 0003: Deterministic feature engine (Phase 3)

## As-of / no-lookahead policy

`compute_feature_snapshot(symbol, timeframe, primary_candles, daily_candles, as_of, config)`
is the single entry point (`app/features/engine.py`). Two things make it
lookahead-safe by construction, not just by convention:

1. **Defense in depth on truncation.** The engine defensively re-filters
   both candle series to `timestamp <= as_of` itself (`truncate_to_as_of` in
   `app/features/common.py`) — it never trusts that a caller already
   truncated. This is the property the backtester will depend on: hand it
   the full history plus a historical `as_of`, and it is structurally
   incapable of seeing later candles, even if the caller has a bug. Proven
   directly in `tests/unit/features/test_engine.py::test_engine_defensively_truncates_even_if_caller_forgot_to`
   and `::test_appending_future_candles_does_not_change_an_earlier_snapshot`.
2. **Two different, deliberate policies for "the latest bar."** Continuous
   features (ATR, moving averages, rolling levels, volume, session-so-far)
   use the most recent *available* candle even if it's still forming as of
   `as_of` — its high/low/volume-so-far genuinely was observable at that
   instant, so this is not lookahead, it's just "today's live reading."
   Discrete pattern features (the latest-candle body/wick/doji
   classification) instead wait for the latest *completed* candle
   (`latest_completed_candle` in `common.py`), since a classification like
   "bullish" shouldn't be allowed to flip mid-bar. `DataQuality.
   latest_candle_is_complete` tells consumers which situation they're in.

## Previous day / previous week

Both avoid a calendar-holiday lookup entirely: "previous trading day" is the
most recent daily candle strictly before today's exchange trading date;
"previous trading week" is the most recent ISO `(year, week)` group strictly
before the current one. Weekends and holidays never produce a candle in the
first place, so "most recent available before today/this-week" already
skips straight past them — a Monday naturally resolves to the prior Friday,
a holiday gap or a multi-day missing-data gap naturally resolves to whatever
session actually exists before it. No special-casing for Mondays or
holidays was needed; see `app/features/previous_period.py` and its test
fixtures (`tests/unit/features/test_previous_period.py`) for the Monday,
holiday-gap, missing-session, and holiday-shortened-week cases this
produces correctly for free.

Previous-day `percent_change` is defined as that day's own return
(`(close - open) / open`), not a change relative to the day before it — it
describes how that single completed session performed.

## Gap definition

Gap = today's regular-session daily bar's `open` minus the previous
completed trading day's `close`. A daily bar's `open` is fixed the instant
the regular session starts and never changes afterward, so using it the
moment today's daily bar exists is not lookahead. Gap is `unavailable`
(not zero) until today's regular session has actually opened. Extended-hours
prices never enter this calculation — `app/features/gap.py` explicitly
requires `session == REGULAR` on today's bar.

## ATR — Wilder smoothing

`True Range[i] = max(high-low, |high-prev_close|, |low-prev_close|)`
(`TR[0] = high-low`, since there's no prior close for the very first bar in
a window — a known, accepted limitation of computing ATR from a fixed
window). ATR uses **Wilder's original smoothing** (not a plain SMA of TR):
seed = simple average of the first `period` true ranges, then
`ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period`. Default period 14,
configurable. Hand-verified against a fully worked 4-bar fixture in
`tests/unit/features/test_indicators.py` and `test_atr.py` (TR=[2,2,5,8],
period=2 → ATR series [None, 2.0, 3.5, 5.75]). Returns
`insufficient_history` rather than a value when fewer than `period` candles
are available — never a fabricated number.

## Moving averages

`ema()`/`sma()` (`app/features/indicators.py`) are generic over any period
and operate on plain float lists. EMA is SMA-seeded at index `period - 1`
(the standard/TradingView convention), not seeded with the first value —
documented because there are multiple valid EMA-seeding conventions and
this one was a deliberate choice for consistency with what most charting
platforms show. The snapshot always reports EMA20/SMA50/SMA200 specifically
(per spec), computed via those generic functions.

## Rolling highs/lows — the include/exclude distinction

`rolling_high`/`rolling_low` take a required `include_current: bool`, and
critically, `RollingLevels` in the output schema carries two **separate**
lists — `including_current` and `excluding_current` — rather than one list
with a boolean flag on each row. This was a deliberate schema choice: a
flag buried in each row is easy to read past when wiring up breakout logic
later; two structurally distinct lists make picking the wrong one much
harder to do by accident.

## Two distinct relative-volume concepts

`VolumeFeatures.relative_volume` compares the current bar's volume against
the average of the `period` bars **immediately preceding** it — the current
bar is never part of its own denominator (`average_volume` in
`app/features/volume.py` explicitly windows `candles[-period-1:-1]`).
`IntradayRelativeVolumeFeature` is a **separate type** with its own name:
cumulative volume from today's regular-session open through the current
bar's time-of-day, compared against the average of the same
cumulative-through-that-time-of-day volume on the last N prior trading days.
It's `not_applicable` for daily/weekly timeframes (the concept doesn't
apply to a single all-day bar) and `unavailable`/`insufficient_history`
rather than a fabricated value when today's session hasn't started or there
isn't enough prior-day history. These two are never allowed to share a name
or a field, specifically so a future setup detector can't accidentally
substitute one for the other.

## Incomplete-candle handling — summary table

| Feature group | Uses the still-forming latest bar? |
|---|---|
| ATR, moving averages, rolling levels, volume, session-so-far | Yes — it's real, observable-as-of data |
| Latest-candle body/wick/classification | No — waits for `latest_completed_candle` |
| Previous day / previous week / gap | N/A — by definition these only ever look at *completed* prior periods |

## Numerical precision

No rounding happens anywhere in `app/features/*` — all values are plain
Python floats at full precision. Rounding is a display concern only,
applied in the frontend's `lib/format.ts`. Tests use `pytest.approx` with an
explicit absolute tolerance rather than `==` on floats throughout.

## Data quality metadata

Every `FeatureSnapshot` carries a `DataQuality` block: candle count,
earliest/latest candle timestamps, whether the latest candle is complete,
its session, how many future candles were defensively dropped, and free-text
warnings. This is what lets a future scoring/AI module know when a feature
is running on thin history rather than silently trusting a number that
might be `insufficient_history` underneath.
