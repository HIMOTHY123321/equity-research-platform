# ADR 0009: trend_pullback episode-identity fix (Phase 8 prerequisite)

## The bug

Phase 7's `trend_pullback` detector (`app/setup_detection/detectors/trend_pullback.py`)
anchored a candidate's identity — `candidate_candle_timestamp`, which feeds
directly into `setup_candidate_id(...)` and `compute_expires_at()` — to
`latest.timestamp`, i.e. "whichever bar is being evaluated right now."
Hard/soft checks correctly re-evaluate the latest bar every step, but tying
*identity* to the same value meant a retracement that stayed valid (or
stayed invalid) for N consecutive bars minted N distinct setup ids for what
a human would call one episode. This was found and deliberately not fixed
during Phase 7 replay validation (ADR 0008) — confirmed on real SPY 1H data
as ~7 candidates across 7 consecutive hourly bars for a single held
retracement.

## The fix: episode-start identity, symmetric on broken state

Identity is now anchored to `episode_start_candle.timestamp`, where
`episode_start_candle` is found by `_episode_start_index` walking backward
from the latest bar while consecutive prior bars share the latest bar's
*broken/unbroken* state relative to the trend's structural invalidation
level (the most recent HL for a bullish trend, LH for bearish). The walk
stops at whichever comes first:

- a **state change** — the invalidation level's broken/unbroken status
  flips relative to the latest bar, or
- the invalidation swing's own `pivot_timestamp` — the earliest instant
  that price level exists as a value at all.

Both are genuine structural boundaries, not arbitrary cutoffs. A
`_MAX_EPISODE_LOOKBACK_BARS = 2000` cap exists purely as a pathological-case
safety net; it is deliberately far larger than any realistic episode so it
is never expected to bind — if it ever does, identity would silently drift
forward one bar per step past it, reintroducing this exact bug.

**Symmetry was not obvious up front and was found by testing against real
data, not designed in from the start.** The first version of this fix only
grouped *unbroken* streaks (walking back "while not broken"), which fixed
the held-retracement case but left an equivalent bug on the rejected side:
real SPY 1H data for 2026-08-14 showed the invalidation level break and
then stay broken continuously from 09:30 to 15:30, and because every prior
bar in that run was *also* broken, the backward walk terminated in zero
steps on every single bar — six distinct rejected candidates for one
continuous break. Generalizing the walk to group on "does this bar's
broken-state match the latest bar's" rather than hardcoding "not broken"
fixed both cases with one rule.

### Why `pivot_timestamp`, not `confirmed_at`

`MarketStructureSwing.confirmed_at` is *later* than `pivot_timestamp` (a
swing isn't confirmed until subsequent bars validate it), so bounding the
backward walk on `confirmed_at` collapsed it to zero steps in the common
case — the walk needs to reach back through the very retracement bars that
occur before the swing is confirmed. `pivot_timestamp` is safe to use here
specifically because this is an identity/display anchor, not a
detection-time anti-lookahead gate: the pivot's price value is real,
already-observed data at any bar where the swing exists in
`structure.latest_higher_low` / `latest_lower_high` at all.

## What did not change

Hard/soft check evaluation (`_check_direction`) still runs entirely against
`latest` — whether a candidate currently qualifies reflects the current
bar, never the episode start. `reference_timestamp` (the swing pivot) and
`invalidation_criteria` are unaffected. `reference_key` is still
`pullback|{pivot_timestamp}`; combined with the new
`candidate_candle_timestamp`, a genuine new episode (state change after a
structural break) still produces a new deterministic id via the existing
`setup_candidate_id` formula — no change was needed there.

## Verification

Against the real SPY 1H fixture (`tests/fixtures/real_market_data.json`,
250 bars): the full-series replay went from minting duplicate ids for both
the original held-retracement case and the newly-found continuously-broken
case, to 25 well-spaced `trend_pullback` ledger entries with no runs of
same-episode duplicates. `tests/unit/setup_detection/test_trend_pullback.py`
adds regression coverage for: stable id across a multi-bar held episode;
no duplicate ledger entries for a held retracement; live-snapshot/replay
parity for the fixed identity; expiration not already past at first
qualification; identity never referencing a bar after `as_of`; and the pure
`_episode_start_index` boundary logic (unbroken streak, structural break,
pivot-timestamp bound) in isolation. Full backend suite (455 tests) and
`ruff check .` both pass clean after the fix.
