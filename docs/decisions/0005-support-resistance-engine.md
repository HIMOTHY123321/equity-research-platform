# ADR 0005: Support/resistance engine (Phase 5)

## Core principle: every zone traces back to evidence

A `Zone` is never a bare price. It is always `member_levels` (the exact
`RawLevel`s that formed it, never deleted or mutated) plus `evidence`
(each member's source, price, and weight) plus `interactions` (every
recorded touch/rejection/wick_breach, independent or not) plus a
`StrengthBreakdown` that sums to `strength.total`. Nothing about "why does
this level exist" is ever thrown away — clustering, strength, and lifecycle
are all *views* over permanent raw evidence, not destructive transforms.

## Raw sources and their `known_at` semantics

`app/support_resistance/sources.py` computes previous-day/previous-week/
session-open levels **directly from daily candles**, not from a
`FeatureSnapshot` — the same reasoning as Phase 4 keeping its own
completeness helpers independent of Phase 3 (see ADR 0004): each engine
owns the minimal as-of-safe primitives it needs rather than depending on
another engine's output shape. `app/support_resistance/multi_timeframe.py`
turns confirmed swings from one or more `MarketStructureSnapshot`s into
`RawLevel`s — this is what lets a single S/R snapshot see a daily swing
high, a 4H swing high, and a 1H swing high *simultaneously*, unlike Phase
4's single "most recent active swing" BOS reference.

| Source | `origin_timestamp` | `known_at` |
|---|---|---|
| Previous day high/low/close | the previous day's own candle | that candle's completion (next calendar day, midnight ET) |
| Previous week high/low/close | the **specific day** within the week that produced the extreme | the whole week's completion (the following Monday, midnight ET) — not the specific day's, since a later day in the same week could still have exceeded it |
| Confirmed swing high/low | `pivot_timestamp` | `confirmed_at` (unchanged from Phase 4) |
| Session open | today's daily bar's own timestamp | the same instant — a session's open print is fixed the moment the session starts and never revised (same reasoning as Phase 3's gap feature) |

`extract_swing_levels` re-filters `swing.confirmed_at <= as_of` itself —
defense in depth even though the `MarketStructureSnapshot`s passed in
should already be as-of safe. `test_invariant_7` in `test_engine.py`
exercises this directly: even a structure snapshot that was (by caller
mistake) computed with a *later* `as_of` than the S/R query's own cannot
leak its confirmed swing into an earlier snapshot.

## Clustering

`app/support_resistance/clustering.py`: single-linkage on price-sorted
levels of one polarity — level *i+1* merges into the current group iff
it's within `cluster_tolerance_percent` (default 0.25%) of the group's
most recently added member. Percentage-based, never a fixed dollar
threshold, so the same tolerance behaves consistently on a $20 stock and a
$500 stock. Support and resistance are clustered independently — a support
and resistance level at the identical price never merge. Reference-kind
levels (previous close, session open) never enter clustering at all.

**Representative price** is source-weighted:
`sum(price * weight) / sum(weight)` across a zone's members, using the
centralized weight table in `config.py` (`get_source_weight`). Weights are
never scattered inline — every lookup goes through one function.

## Zone identity

Level IDs are deterministic composite keys: `f"{source}|{timeframe}|{origin_timestamp.isoformat()}"`
— never random UUIDs, so the same historical data recomputed at any later
time produces the identical ID (`ids.py`). Zone IDs are a short SHA-256
hash of their **sorted** member level IDs, prefixed with the zone's
polarity. This means zone identity is a pure function of exactly which
evidence it contains: the same set of members always produces the same ID
regardless of processing order (`test_stable_ids_across_recomputation`),
and a zone whose membership changes (a new level joins, or the tolerance
config changes) gets a *different* ID — which is correct, since it's
structurally a different zone.

## Interaction detection: touch / rejection / wick_breach / close_break

`close_break` is detected separately (`breaks.py`) and takes precedence —
`interactions.py` receives a `stop_at` timestamp and never classifies a
candle at or after the break. Among the rest, precedence is
**rejection > wick_breach > touch**: a candle that pokes through the zone
*and* closes back past the representative price is a clearer, more
informative signal than a plain wick poke that doesn't fully reject, so it
is classified as the stronger label even though it also satisfies the
weaker one.

- **Rejection** (`rejection.py`, deliberately just two objective
  predicates, no subjective candlestick naming): the candle overlapped the
  zone and its close failed to hold beyond the representative price
  (`close < representative_price` for resistance, mirrored for support).
- **Wick breach**: the candle's high/low poked beyond the zone boundary but
  the close didn't confirm a rejection or a break.
- **Touch**: the candle simply overlapped the zone (within
  `touch_tolerance_percent`, default 0.1%) without qualifying as either of
  the above.

**Independent-interaction separation**: consecutive interactions within
`minimum_bars_between_independent_touches` (default 3) bars of the prior
one are folded into the same event — still recorded in full (for later
research), but flagged `is_independent=False`. Only independent
interactions count toward strength or the displayed touch/rejection
counts, so five candles consolidating at one price never reads as five
confirmations.

## Break definition

Same discipline as Phase 4's BOS: `close > upper_bound * (1 +
break_tolerance_percent/100)` for a resistance break (mirrored, `<`, for
support), default tolerance 0% — a wick-only move never counts, and exact
boundary equality never counts (strict inequality). A zone breaks at most
once; the first qualifying close is recorded and nothing after it matters.

## Strength model — fully worked example

Every point is explainable via `StrengthBreakdown`; the total is never
called a probability anywhere in this codebase.

```
Previous week high          +25   source_score  ┐
Daily swing high             +18   source_score  ├─ 55 (capped at 60)
4H swing high                 +12   source_score  ┘
Multi-timeframe confluence    +10   confluence_score (3 timeframes: (3-1)*5)
3 independent rejections      +12   interaction_score (6+4+2, see below)
Recency (touched 3 bars ago)   +5   recency_score
------------------------------------
Total                          82
```

This exact breakdown is asserted byte-for-byte in
`test_strength.py::test_full_worked_example_matches_adr`.

- **Source score**: sum of member weights, capped at 60.
- **Confluence score**: `(timeframe_count - 1) * 5`, capped at 15. Requires
  more than one *timeframe* (not source) among the zone's members —
  three daily levels clustered together contribute 0 confluence, since
  they're not independent timeframes agreeing.
- **Interaction score — diminishing returns**: rejections and touches each
  follow their own fixed points schedule, applied in order to independent
  events only: rejections `[6, 4, 2]` (1st, 2nd, 3rd; 4th+ contribute
  nothing further), touches `[3, 2, 1]`. Combined score is capped at 18.
  Fifteen touches can never produce an unbounded score — the schedule's
  length is the real cap, and slicing a Python tuple past its length is
  safe and simply stops contributing.
- **Recency score**: bucketed by bars since the last independent
  interaction (or since creation if never touched): ≤3 bars → 5, ≤10 → 3,
  ≤30 → 1, else 0.
- **Broken penalty**: a broken zone's total strength is multiplied by 0.3
  (documented constant `BROKEN_ZONE_PENALTY_MULTIPLIER`) rather than zeroed
  — a zone that broke after three prior rejections is still meaningfully
  different, for research purposes, from one that never had any evidence
  at all.
- Total is clamped to 100.

## Lifecycle

`app/support_resistance/lifecycle.py`, evaluated in this precedence
(mutually exclusive, first match wins): **broken** (has a recorded break
event, regardless of anything else) → **stale** (more than
`stale_after_bars`, default 100, bars since the last independent
interaction, or since creation if never touched) → **weakened** (≥4
independent interactions and still unbroken — the same threshold where the
interaction-score schedule stops adding points, signaling "this level has
been tested enough that further tests don't add confidence, and may
increasingly threaten it") → **tested** (≥1 independent interaction) →
**active** (freshly created, never touched). Broken zones are never
deleted — they move to `recent_broken_zones` in the snapshot, preserving
exactly the historical-research use cases the phase calls for ("how often
does a 3-touch zone break on the 4th test?").

**Freshness anchoring — the Phase 4 bug, not repeated**: `bars_since_*` is
computed over `zone_candles`, the *already-filtered* slice of primary
candles from `zone.known_at` through `as_of` (completed bars only) — never
the raw as-of-truncated series, which can vary by whether a still-forming
trailing candle happened to be included. Because the caller passes exactly
that eligible slice, `bars_since_created` is simply `len(zone_candles) - 1`,
with no special-casing needed. See ADR 0004 for the original bug this
mirrors and avoids.

## Nearest-zone rules

`nearest_resistance_above`/`nearest_support_below`/`nearest_active_zone`
(`nearest.py`) exclude `broken` and `stale` zones by construction and are
purely distance-based — a closer weak zone always beats a farther strong
one for "nearest" (strength has no say in proximity; it's a separate,
explicit field on each zone). `PriceRelationship.position` is
`above_price`/`below_price`/`contains_price`, purely descriptive — no
trade direction is ever implied.

## Relevance ranking (bounded snapshot, unbounded evidence)

The full zone set is always computed; only the top
`max_zones_in_snapshot` (default 8) per polarity are returned in the API
snapshot, ranked by `strength.total - min(distance_percent * 2, 40)` — a
very strong zone 40%+ away is penalized enough that a moderate, nearby zone
still surfaces ahead of it, per the phase's explicit instruction not to
just show the strongest N regardless of relevance. `nearest_support`/
`nearest_resistance` are computed from the *full*, unbounded active-zone
set before this truncation, so they're always correct even if the true
nearest zone didn't make the top-8 cut by strength.

## Polarity flips — deferred, not guessed

The `Zone`/`Zone.kind` schema and lifecycle model are designed so a future
resistance→support flip rule could slot in (a broken resistance zone,
successfully retested and held from above, becoming support) — but that
rule is **not implemented** in Phase 5. A broken zone stays recorded with
`kind` unchanged and `lifecycle=broken`; nothing automatically relabels it.
This is a deliberate deferral per the phase's own instruction not to use
vague "support became resistance" logic without an exact rule.

## Chart architecture refactor (#38/#39)

Implemented, not deferred. `MarketWorkspace` now owns all four market-data
requests (`useCandles`/`useFeatures`/`useStructure`/`useLevels`, sharing
one generic `useAsyncResource` hook) and passes results down as props —
`FeaturePanel`, `StructurePanel`, and the new `SupportResistancePanel` are
now purely presentational, and `CandlestickChart` receives the same
`structure`/`zones` data the panels use for chart overlays, so there is
exactly one `/structure` and one `/levels` request per symbol/timeframe
change, never a second one just for chart markers.

Overlays: swing markers (`HH`/`HL`/`LH`/`LL`/`SH`/`SL`) and BOS/CHOCH
arrows are placed via Lightweight Charts' `createSeriesMarkers` API at
`pivot_timestamp`/`break_timestamp` — the instant the event actually
happened — never at `confirmed_at`, so the chart never visually implies a
swing was known before it was confirmed. Zones are drawn as a pair of
dashed `createPriceLine` boundaries (not a filled band — the free
Lightweight Charts build has no built-in filled-region primitive) for only
the top 6 zones by strength, keeping the chart readable rather than a wall
of lines.

## Anti-lookahead guarantees

Same defense-in-depth pattern as Phases 3-4: every candle series is
re-truncated to `as_of` and to completed-only bars inside the engine
itself, regardless of what the caller passed. A zone's own eligible-candle
window additionally starts at `zone.known_at` (the latest `known_at` among
its members) — a zone can never appear to have been "touched" before it
structurally existed, even though its bounds are (deliberately) evaluated
against the zone's *current* composition rather than simulating how the
zone's membership would have evolved bar-by-bar through history. That's a
documented simplification, not a lookahead gap: both the zone definition
and the interaction history are still built entirely from data `<= as_of`,
so nothing from the future ever enters the calculation — see
`test_engine.py`'s eight mandatory invariant tests for the full proof,
including one (`test_invariant_1`) that caught the same
"one extra still-forming candle available" nuance documented in ADR 0004,
resolved the same way: excluding the informational fields that legitimately
vary with how much raw data was fetched, while asserting the actual zone
evidence matches byte-for-byte.
