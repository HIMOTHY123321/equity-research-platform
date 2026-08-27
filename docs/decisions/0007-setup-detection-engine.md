# ADR 0007: Setup detection & qualification engine (Phase 6)

## Core principle: detection and qualification are two different questions

"Price closed beyond a level" is a **detected pattern**. "This is a setup
worth acting on" is a **qualified setup**. Every other trading tool
conflates these into one boolean; this one deliberately doesn't. A single
`SetupCandidate` record carries both: `hard_checks` (what a pattern
requires to count at all) and `soft_checks`/`conflicts` (what strengthens
or weakens it without erasing it), with `current_state` recording where the
candidate landed. A candidate that fails a hard check isn't discarded — it
becomes a `REJECTED` record with the exact failed check attached, which is
the entire mechanism behind the "why not?" engine (see below).

## Candidate lifecycle

States: `candidate → qualified → triggered → invalidated / expired`, or
`candidate → rejected`. Never a boolean. Every transition is a
`LifecycleTransition{state, timestamp, reason_code, reason_label}` — never
backdated to the pattern's original candle. Two shapes exist:

- **Single-transition** (`detectors/_common.py::build_resolved_candidate`):
  the trigger condition and its confirmation are the same completed candle
  (a PDH close-breakout, a resistance rejection interaction). Goes straight
  to `QUALIFIED` or `REJECTED` at that bar.
- **Multi-stage**: `breakout_retest` (candidate at the breakout bar →
  qualified/rejected at the *later* retest bar, whichever bar that turns
  out to be) and `failed_breakout`'s `confirmed_breakout_failure` variant
  (candidate → triggered at the breakout → invalidated at a later reversal
  bar). Both walk candles chronologically, exactly like Phase 4's BOS
  simulation — the system never "knows" a retest is coming before it
  happens in the data.

`gap_fill` is a third shape: tracked rather than pass/fail. A qualifying
gap is always `QUALIFIED` the moment it's detected (there's no "reject" a
gap), then `TRIGGERED` the instant a later candle actually trades back
through the previous close — found by scanning today's candles for that
exact bar, not inferred.

## Evidence model

Every candidate carries `hard_checks: EvidenceCheck[]`, `soft_checks:
EvidenceCheck[]`, and `conflicts: ConflictCheck[]` (see
`app/setup_detection/evidence.py` and `conflicts.py` for the shared
builders every detector composes from). `EvidenceCheck.label` is a
deterministic f-string built from real fields (`code`, `actual`,
`required`) — never generated prose, matching the convention
`TrendClassification.evidence` already established in Phase 4.

## Hard vs. soft, and why a failed soft check never blocks

`qualification.py::is_qualified` is one line: `all(c.passed for c in
hard_checks)`. Soft checks and conflicts are evaluated and recorded
regardless of qualification outcome. A real example from live NVDA data:
a `resistance_rejection` candidate qualified with **zero** soft checks
passing (RVOL below threshold, daily structure opposed, zone strength
below the "moderate" bar) and one `MAJOR` conflict recorded (daily
structure bullish against a bearish setup) — it still qualifies, because
the one hard requirement (an independent rejection interaction actually
occurred) was satisfied. The UI shows all of this; nothing is hidden to
make the setup look cleaner than it is.

## The "why not?" engine

A `REJECTED` candidate's `hard_checks` list always contains at least one
`passed: false` entry with `code`, `actual`, and `required` populated —
`tests/unit/setup_detection/test_real_data_regression.py::
test_rejected_candidates_always_explain_which_hard_rule_failed` asserts
this holds for every rejected candidate produced against real SPY/QQQ/NVDA
data. `wick_failed_breakout` (a wick beyond a level that never closes
beyond it) is `failed_breakout.py`'s dedicated near-miss detector for
exactly the case the Phase 6 spec's own TSLA example describes.

## Every detector, one line each

| Detector | Hard rule | Reuses |
|---|---|---|
| `previous_day_breakout` | Completed close beyond PDH/PDL | `FeatureSnapshot.previous_day` |
| `previous_week_breakout` | Completed close beyond PWH/PWL | `FeatureSnapshot.previous_week` |
| `breakout_retest` | Confirmed breakout, then a later bar revisits and holds/fails | close-beyond-level primitive |
| `failed_breakout` | Wick without close (rejected immediately), or a confirmed close that reverses within N bars (invalidated) | close-beyond-level primitive |
| `support_reclaim` | Genuine prior close below the reference within the lookback, then a close back above | Phase 5 nearest/recently-broken support zones, PDL fallback |
| `resistance_rejection` | A real `ZoneInteraction(REJECTION, is_independent=True)` on an active resistance zone | Phase 5 interaction events directly — no competing rejection rule |
| `gap_continuation` | Qualifying gap size, not mostly filled, still holding beyond session open | `FeatureSnapshot.gap` + `.session` |
| `gap_fill` | Qualifying gap exists (tracked); triggers when a candle trades through previous close | `FeatureSnapshot.gap` |
| `liquidity_sweep` | Wick through a **already-confirmed** swing, close back beyond it | `MarketStructureSnapshot.swings` + explicit `confirmed_at` guard |
| `moving_average_reclaim` | Previous completed candle on one side of EMA20/SMA50/SMA200, current candle closes on the other | `app.features.indicators.ema/sma` (point-in-time) |
| `trend_pullback` | Established trend, retracement reaches a real S/R reference, trend's own structural invalidation level (latest HL/LH) not broken | `MarketStructureSnapshot.latest_higher_low/lower_high` |
| `range_breakout` | Completed close beyond `MarketStructureSnapshot.active_range`, **only after** the range's defining swing's own `confirmed_at` | Phase 4 active-range directly |

No detector recomputes previous-day/week levels, gap math, MA math, S/R
zones, or swing/BOS/CHOCH logic — every hard rule is built from an already
lookahead-safe Phase 3-5 output plus the shared `evidence.py`/`conflicts.py`
primitives.

## Conflicts

`conflicts.py` provides reusable, structured builders: higher-timeframe
opposition, an opposing zone sitting too close to the reference price, data
quality warnings, and candidate staleness. Severity is `MAJOR`/`MINOR`, not
a synonym for pass/fail — a conflict is always informational (see above).

## Setup expiration

`lifecycle.py::compute_expires_at` turns `default_candidate_expiration_bars`
(20, overridable per `SetupType` via `config.candidate_expiration_bars_by_type`)
into a real timestamp using the primary timeframe's bar duration. Only
`CANDIDATE`/`QUALIFIED` candidates can expire (`engine.py::_apply_expiration`)
— a `REJECTED`, `INVALIDATED`, or `TRIGGERED` candidate is already terminal
and never gets a synthetic `EXPIRED` transition layered on top.

## Duplicate-signal suppression

No detector creates a second candidate for the same open reference cycle.
Single-transition detectors `break` after the first triggering bar per
reference level (e.g. `previous_day_breakout` — the first close beyond PDH
opens the candidate; the day's remaining bars closing above it don't spawn
five more). `liquidity_sweep` tracks a `seen_swings` set **keyed by swing
identity alone** (not swing+candle) across its whole scan — a real bug,
found while writing this detector's tests, initially keyed the set by
`(candle.timestamp, swing_key)`, which let the *same* swing low re-trigger
a new candidate on every subsequent bar that also happened to wick below
and reclaim it (observed on live SPY data: four near-duplicate bullish
sweep candidates for the same 763.48 level across four consecutive hourly
bars). Fixed by dropping the timestamp from the dedup key.

## Fingerprints

`fingerprint.py::build_fingerprint` buckets (never raw floats) `setup_type`,
`direction`, multi-timeframe trend, an RVOL bucket, gap state, and
distance-to-nearest-opposing-zone buckets. No historical performance is
attached — this is feature extraction for a future analog search, nothing
more (explicitly out of scope for Phase 6, per the spec).

## Market context (deliberately unwired)

`SetupContext.market_context: Optional[MarketContext]` and
`SetupDetectionConfig.benchmark_symbol: Optional[str]` exist so a future
phase can add SPY/QQQ-relative context to individual-equity setups without
a schema migration. `benchmark_symbol` defaults to `None` and
`market_context` is never populated in Phase 6 — wiring it would mean a
second live market-data fetch on every `/setups` call for every symbol,
which is real added latency/complexity the spec explicitly said could
wait ("full market-relative scoring can wait").

## Invalidation semantics

Every qualified candidate carries `invalidation_criteria: list[str]` —
deterministic, template-built statements of what would invalidate this
*specific* pattern (e.g. "Confirmed close back below 763.48"), answering
the spec's "what would invalidate the pattern?" requirement directly from
the same values used to qualify it. This is structural invalidation, not a
stop-loss recommendation — no position sizing or price-target logic exists
anywhere in this package.

## Anti-lookahead guarantees, and two real bugs found enforcing them

Every detector reads only `completed`, `as_of`-truncated candles
(`engine.py` truncates once, centrally, reusing
`app.market_structure.common` — this package depends on Phase 4's common
module the same way Phase 5 already does, rather than re-duplicating a
third copy of `truncate_to_as_of`/`completed_only`). Two bugs were found
this way while building the mandatory anti-lookahead tests, both against
real SPY data:

1. **`range_breakout` boundary lookahead.** `MarketStructureSnapshot.
   active_range` is a single *current* value; the detector was checking
   every candle in the lookback window against it, including candles from
   **before** the range's own defining swing was confirmed. A real
   SPY candle from 2026-08-19 traded above what later became "today's"
   765.59 active-range high — five days before that swing even existed.
   Fixed by gating on `candle.timestamp >= defining_swing.confirmed_at`.

2. **Previous-day/week reference-period lookahead**, found identically in
   `previous_day_breakout`, `previous_week_breakout`, `breakout_retest`,
   `failed_breakout`, and `support_reclaim`'s PDL fallback path. Each was
   scanning its full `detection_lookback_bars` window (~8-9 trading days)
   against a *single* `FeatureSnapshot.previous_day`/`previous_week` value
   — but that value is only a valid reference starting the very next
   trading day/week. Confirmed on real SPY data: candles from 2026-08-19
   and 2026-08-20 were being checked against 2026-08-21's previous-day
   high, which didn't exist for either of them. Fixed with two shared
   guards in `detectors/_common.py` — `after_previous_day`/
   `after_previous_week` — applied everywhere a previous-day/week level is
   used as a reference. `support_reclaim`'s zone-based path got the
   equivalent fix: a candle before `zone.known_at` can't reference that
   zone as "support" yet.

The 10 mandatory anti-lookahead tests (`test_anti_lookahead.py`) all run
against real SPY data rather than synthetic fixtures, specifically because
these two bugs would not have been caught by synthetic data small enough to
hand-construct — they only appeared once the window was wide enough to
contain multiple trading days/weeks with real, non-trivial price action.

## Worked example (chronological)

Real NVDA 1H data, `previous_week_low_breakdown`:

```
2026-08-19  Previous week (Aug 11-15) low = 214.50 confirmed at week close.
2026-08-19 07:00  Candle closes at 214.50 -- exactly equal, does NOT count
                   (close-only, exact equality never counts, per #7).
2026-08-19 08:00  Wicks to 213.90, closes at 214.65 -- still above, no break.
2026-08-19 07:00  [separately] a wick to 213.5 without a qualifying close
                   -> wick_failed_breakout, REJECTED immediately.
2026-08-19 07:00  A later completed candle closes at 214.20 -- confirmed
                   breakdown. previous_week_low_breakdown candidate created
                   AND qualified at this same instant (candidate_at ==
                   qualified_at, since confirmation and detection coincide
                   for a single-transition detector).
2026-08-19 08:00  Price closes back above 214.50 within failed_breakout_bars
                   -> a SEPARATE confirmed_breakout_failure candidate is
                   also produced by failed_breakout.py, INVALIDATED at that
                   bar -- both records coexist; neither overwrites the other.
```

## Performance

`/setups` warm response: ~120-170ms for SPY/1h (2000 candles, 12
detectors). Cold (including the yfinance fetch): ~1.5-2.4s across
SPY/NVDA/QQQ and 1D/4H/1H/5m — detection itself is cheap relative to
market-data fetching, per the spec's requirement. The one detector that
initially risked pathological cost, `moving_average_reclaim` (point-in-time
EMA/SMA recomputation per candle), is bounded to `detection_lookback_bars`
candles rather than the full multi-thousand-candle history — confirmed via
a live 5m/SPY run (11,326 candles, 12 detectors, 1.5s total, dominated by
the cold candle fetch, not detection).

## What's honestly out of scope / simplified

- Most single-condition detectors (PDH/PWH breakout, range breakout,
  support reclaim, resistance rejection, liquidity sweep) only ever build a
  candidate once their trigger condition is observed — they don't emit a
  `REJECTED` twin for every bar that shows no sign of the pattern at all.
  "Why not?" coverage is concentrated in `failed_breakout.py` (both
  variants), `breakout_retest.py`'s failed-hold branch, and
  `gap_continuation.py`'s multi-hard-check design, which are the
  detectors whose near-misses are actually meaningful to a trader — a
  bar that never approached a level isn't an interesting rejection.
- `MarketContext`/benchmark-relative context is schema-ready but not
  wired (see above).
- A shared `_CandleCache` (`api/routes/market.py`) memoizes candle/structure
  fetches within a single `/setups` or `/levels` request — a small,
  targeted orchestrator per the spec's "consider a small shared
  orchestrator... but do not over-engineer" guidance, not a general
  caching framework.
