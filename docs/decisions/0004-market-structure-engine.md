# ADR 0004: Market structure engine (Phase 4)

## The core distinction: `pivot_timestamp` vs `confirmed_at`

This is the single most important design decision in this package. A swing
high/low candidate at candle index `i` needs `right_bars` complete candles
after it before the pivot rule can be fully evaluated — until then, its
existence isn't knowable yet, even though the candle itself already printed.

- **`pivot_timestamp`** — the timestamp of the candidate candle itself. This
  never changes once a swing is confirmed.
- **`confirmed_at`** — the earliest instant the pivot could legally have been
  known, computed as `candle_complete_at(candles[i + right_bars])`: the
  moment the *last required right-side candle* itself finishes forming (its
  own start time plus its timeframe's duration for intraday bars, or the
  next calendar day at midnight ET for daily bars).

Example (`left_bars = right_bars = 2`, 1H candles):

```
Candle 10 (14:30) = candidate swing high
Candle 11 (15:30), Candle 12 (16:30) = right-side confirmation candles
```

At `as_of = 16:00` (candle 12 hasn't completed yet): the pivot is not
returned as confirmed structure at all — it may appear in `candidate_swings`
if it currently looks like a local extreme using only the right-side bars
available so far, but never in `swings`.

At `as_of = 17:31` (candle 12 completed at 17:30): the swing appears with
`pivot_timestamp = 14:30` (unchanged) and `confirmed_at = 17:30` (candle
12's own completion instant, not candle 12's start time — a subtlety worth
getting right, verified in `test_swings.py`).

## As-of / no-lookahead policy (same discipline as Phase 3, reimplemented independently)

`app/market_structure/common.py` deliberately does **not** import
`app/features/common.py`, even though the logic is nearly identical (per
this phase's explicit scope: keep the two engines separate). Every engine
entry point:

1. Defensively re-truncates its candle input to `timestamp <= as_of` itself.
2. Further drops any trailing still-forming candle (`completed_only`) —
   swing/BOS/CHOCH detection never touches a candle whose high/low/close
   could still change. This is a stricter policy than Phase 3's features
   (which intentionally *do* use a forming candle for continuous values like
   ATR) — here, every output is a discrete structural claim ("this is a
   swing", "this level broke"), and those shouldn't be allowed to flip
   later because a partial bar kept moving.

A subtle bug this caught during development: `Freshness` ("bars since X")
was initially anchored on the raw as-of-truncated candle list, which can
legitimately contain one extra still-forming candle depending on how much
raw data a caller happened to fetch. That made "bars since" counts vary
based on incidental data availability rather than being purely
`as_of`-and-data determined. Fixed by anchoring `Freshness` on the same
`completed` candle list everything else uses — see
`test_engine.py::test_invariant_4_appending_future_candles_does_not_change_earlier_snapshot`,
which is what surfaced it.

## Swing algorithm: pivot/fractal with an explicit tie rule

Candle `i` is a swing high if, within `[i-left, i+right]`:
`candles[i].high` is strictly greater than every left-side bar's high, and
greater-than-or-equal to every right-side bar's high (mirrored for lows,
with the inequality direction flipped). Concretely:

```python
is_pivot_high = all(c.high < pivot for c in left_bars) and all(c.high <= pivot for c in right_bars)
```

**Tie convention**: when two neighboring bars share the exact same extreme
price, the *earliest* (leftmost) bar wins — implemented as the asymmetric
strict-left/non-strict-right comparison above, not a separate tie-break
pass. If bar `i` and bar `i+1` both have high `184.25`, bar `i` qualifies
(its right-side check allows the tie) and bar `i+1` does not (its left-side
check requires the earlier bar to be *strictly* lower, which it isn't).
This is deterministic, requires no extra bookkeeping, and is tested in
`test_swings.py::test_equal_high_tie_earliest_bar_wins`.

`left_bars`/`right_bars` default to 2/2 and are fully configurable per call
via `MarketStructureConfig` — never hard-coded in the detection logic.

## HH/HL/LH/LL classification

A confirmed swing is compared only to the previous **confirmed swing of the
same type** in pivot-chronological order — highs are never compared to
lows. Equality uses a percentage tolerance
(`MarketStructureConfig.equal_tolerance_percent`, default 0.1%), not raw
float equality, since two swings a few cents apart on a $400 stock are
economically equal even though they're never bit-identical floats:
`|price - previous| / |previous| * 100 <= tolerance`. The very first swing
of a given type has no prior swing to compare against, so its
`classification` is `null`.

## Trend classification

Only the most recent `structure_lookback_swings` (default 4) *classified*
swings are considered — a single old pivot can't keep flipping the regime
forever. Within that window:

- **Bullish**: HH/HL evidence outnumbers LH/LL evidence.
- **Bearish**: LH/LL evidence outnumbers HH/HL evidence.
- **Ranging**: bullish- and bearish-type evidence are tied (including a genuine 0-0 tie from only equal highs/lows — no directional evidence at all).
- **insufficient_data**: fewer than 2 classified swings in the window (or none at all).

> **Addendum (yfinance real-data validation checkpoint, 2026-08)**: the rule
> above was originally unanimity-based ("at least one HH/HL, and *zero*
> LH/LL" — a single contradicting swing forced `ranging`). Real yfinance
> data for SPY/QQQ/NVDA on both 1D and 1H consistently showed a 3-bull/1-bear
> evidence split (e.g. `HH, LH, HL, HH`) being forced to `ranging` despite an
> unambiguous bullish EMA20>SMA50>SMA200 stack from the feature engine
> underneath — one minor pullback swing was overriding three pieces of
> confirming evidence. Verified across all six real symbol/timeframe
> combinations before changing anything (per the checkpoint's "test across
> multiple symbols/timeframes and document the reason" requirement, not a
> single-chart tuning decision). Fixed to majority-wins in
> `app/market_structure/classification.py::classify_trend`; a genuine tie
> (equal bull/bear evidence, including 0-0) still correctly falls through to
> `ranging`. All 71 pre-existing tests passed unchanged (none exercised a
> non-tied contradiction), and two new tests
> (`test_majority_bullish_evidence_wins_over_a_single_contradicting_swing`,
> `test_majority_bearish_evidence_wins_over_a_single_contradicting_swing`)
> lock in the new behavior.

Strength (`weak` / `developing` / `established`) is a deterministic count of
supporting evidence pieces against configurable thresholds
(`developing_evidence_count` default 2, `established_evidence_count`
default 3) — never a fabricated percentage. `evidence` is a list of
human-readable strings (`"HH at 190.15"`) built directly from the swings
that drove the classification, so the "why" is always inspectable.

## Break of Structure (BOS)

A **sequential, chronological simulation**, not a "diff the final state"
calculation — this distinction is what keeps it lookahead-safe. Walking
candles in order: a swing only becomes the "active" reference level once
its own `confirmed_at` has passed (using the breaking candle's own
completion instant as the comparison point — see `breaks.py`), and only the
single most-recently-confirmed, not-yet-broken swing of each type (high or
low) is tracked as that reference. A newer confirmed swing silently
replaces an older unbroken one as "the relevant most recent confirmed swing
high" — this matches the spec's phrasing directly and keeps the rule
simple: at any instant there is at most one active bullish reference level
and one active bearish reference level.

Default confirmation is `close`: `candle.close > level * (1 +
bos_tolerance_percent / 100)` for a bullish break (mirrored for bearish). A
wick through the level is never enough on its own. `bos_tolerance_percent`
defaults to `0.0`, meaning any strictly-beyond close counts and **exact
level equality never counts** (`close > level`, not `>=`). Once a swing is
broken, it's recorded once — a `broken_pivots` set (rederived fresh from
the event list each call, not mutable global state) prevents every
subsequent candle above the same level from re-triggering.

`apply_break_state()` re-annotates each `SwingPoint` (`is_broken`,
`first_broken_at`, `break_direction`) from the event list, also rederived
fresh rather than mutated.

> **Addendum (yfinance real-data validation checkpoint, 2026-08)**:
> `apply_break_state()`'s lookup dict was originally keyed by
> `pivot_timestamp` alone. Real SPY 1H data on 2026-08-24 produced a swing
> HIGH (765.72) and a swing LOW (763.0112) sharing the identical
> `pivot_timestamp` (07:00 ET) — a legitimate outcome, since a single
> wide-range candle can be both a swing high and swing low pivot at once. A
> genuine bearish break of the LOW was incorrectly also applied to the
> unrelated HIGH, surfacing as a structurally-impossible
> `break_direction=BEARISH` on a swing high (a bullish BOS event can only
> ever describe a broken swing high, and vice versa — see
> `detect_breaks_of_structure` above). Fixed by keying the dict as
> `(swing_type, pivot_timestamp)`, deriving the expected type from each
> event's `direction`. Regression test:
> `test_apply_break_state_does_not_cross_contaminate_high_and_low_at_the_same_pivot_timestamp`
> in `tests/unit/market_structure/test_breaks.py`. Full suite (357 tests)
> and `ruff check .` both pass after the fix.

## Change of Character (CHOCH)

An exact rule, not vague discretionary terminology: while the
currently-classified trend (re-evaluated at each swing confirmation, using
the *same* `classify_trend()` the snapshot itself reports) is **bullish**, a
decisive close below the most recently confirmed swing low classified as a
**Higher Low (HL)** is a bearish CHOCH. While trend is **bearish**, a close
above the most recently confirmed swing high classified as a **Lower High
(LH)** is a bullish CHOCH. A swing that isn't classified HL/LH is never a
CHOCH reference, even if it's the most recent swing overall — CHOCH
specifically watches "the swing that would have to break for this trend
call to be wrong." If trend never reaches bullish/bearish, or no
qualifying HL/LH exists yet, no CHOCH is emitted — never guessed. Same
close-only confirmation and one-event-per-level rules as BOS.

## Active range

Bounded by the single most recent confirmed swing high and swing low
(regardless of which came first chronologically) — not a
support/resistance clustering system, which is a later phase.
`width_percent` is relative to the range low (a stock-agnostic, consistent
convention); `position_percent` locates the latest available price (which
may be from a still-forming bar — this is a continuous "where are we right
now" value, not a discrete structural claim) between 0% (at the low) and
100% (at the high). Returns `insufficient_data` if either side is missing,
or if the most recent low happens to sit at or above the most recent high
(can happen with unusual/thin data — no sensible box to report).

## Multi-timeframe summaries

Each timeframe's snapshot is computed by an entirely independent call to
`compute_market_structure_snapshot` — no shared state crosses timeframes,
so one timeframe's data can never influence another's (see
`test_invariant_8_*` in `test_multi_timeframe.py`). `higher_timeframe_alignment`
is a plain, explicit rule — `"aligned"` only when daily and 4H trend are
both present, both directional (bullish or bearish, not
ranging/insufficient), and equal; `"mixed"` otherwise; `null` if either
timeframe is missing from the request. No combined trade bias is produced,
and never will be by an AI in this layer.

## Deferred: chart pivot markers

Phase 4's frontend adds a Market Structure panel (trend, latest swings,
last BOS/CHOCH, active range, recent events) but does not yet overlay
markers on the candlestick chart. Doing so cleanly would require lifting
structure-fetching out of `StructurePanel` and into `MarketWorkspace` (to
avoid fetching `/structure` twice) and extending `CandlestickChart`'s
props — a real architectural change, not a small addition — so per the
phase's explicit allowance, it's deferred rather than rushed. When it lands,
markers must be placed at `pivot_timestamp` while any tooltip/label data
keeps `confirmed_at` visibly separate, so the chart never visually implies
a pivot was known before it actually was.
