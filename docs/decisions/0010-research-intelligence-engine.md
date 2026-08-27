# ADR 0010: Statistical validation & research intelligence engine (Phase 8)

## Scope and non-goals

This phase turns Phase 7's historical replay/ledger/outcome evidence into
research statistics: distributions, matched baselines, bootstrap intervals,
signal decay, excursion/first-hit path analysis, temporal and cross-symbol
stability, sample-concentration warnings, a deterministic historical analog
engine, standardized evidence cards with quality flags, research
contradictions, and immutable research snapshots. It deliberately does
**not** add AI analysis, ML prediction, arbitrary 0-100 scoring, automated
parameter optimization, paper/real trading, position sizing, or a
"best strategy" leaderboard — those remain out of scope until (if ever) a
future phase, and only after the evidence built here is judged strong
enough to justify it (see the completion report's recommendation).

All new logic lives in `app/research_intelligence/`, a package that sits
*above* `app.research` and `app.setup_detection` — it reads already-persisted
`SetupLedgerEntry`/`SetupOutcome` records and Phase 7's replay engine, and
adds no new detection or evaluation logic of its own. Where Phase 7 already
had a primitive (baselines, qualification lift, rejection value, sample-size
labels, config hashing, dataset provenance), this phase composes on top of
it rather than re-implementing it — several Phase 7 helper functions were
renamed from private to public (`stats_over_indices`, `horizon_values`,
`forward_candles`, `directional_delta`) specifically so this package could
reuse them instead of duplicating the logic.

## Prerequisite: trend_pullback duplicate-candidate fix

See ADR 0009 for the full writeup. Summary: candidate identity was
re-anchored from "whichever bar is latest" to "the start of the current
streak of bars sharing the same broken/unbroken state relative to the
trend's structural invalidation level" — fixing both a held-retracement
duplicate bug (Phase 7's known limitation) and a second, symmetric bug found
during this phase's verification (a continuously-broken invalidation level
minting a new rejected candidate every bar). Verified against the full real
SPY 1H fixture: duplicate-episode ledger entries eliminated with no loss of
genuine new-episode detection.

## Provider capability (#2)

`app/research_intelligence/provider_capability.py` holds static, hand-updated
capability data from a live yfinance investigation (2026-08-25, real SPY
data, same call shape the app's provider uses): 1D effectively unlimited,
1H ~730 reliable calendar days, 15m/5m ~60 reliable calendar days. An
undocumented quirk was found and deliberately not relied on: the
`period="730d"`/`period="60d"` **string** this app's provider requests
empirically returns *more* history (~1063 days for 1h, ~85 days for 15m/5m)
than an explicit `start=`/`end=` range of the same nominal length allows —
`max_reliable_lookback_days` uses the conservative, documented figure, not
the larger observed one, so research conclusions never depend on unstable
provider behavior. 1H is confirmed as the right primary research timeframe:
enough reliable history for a meaningful chronological partition split.

## Dataset: universe, manifest, partitions (#3, #4, #5)

`ResearchUniverse` is a plain, explicit, caller-supplied symbol list —
never hardcoded in an engine. The default (SPY/QQQ/NVDA/AAPL/MSFT/META/AMZN/
TSLA) lives in `ResearchIntelligenceConfig`, not scattered across call
sites. `DatasetManifest` reuses Phase 7's `DatasetProvenance` per symbol
(same SHA-256 candle-content hashing) and aggregates it with `config_hash`,
`app_version` (hand-synced from `pyproject.toml`, same convention as
`app.research.config`'s `candle_window_by_timeframe`), and the universe's
date-selection rule, so a research run's dataset is always exactly
reconstructable later.

Partitions (`partitions.py`) are chronological, contiguous, and never
shuffled: bar count is split development/validation/test by configurable
ratios (default 60/20/20), with the test partition absorbing any rounding
remainder so every bar is accounted for exactly once. This is architecture
only — nothing in Phase 8 optimizes using this split; it exists purely so a
rule's behavior can be checked out-of-sample rather than validated against
the same data it was eyeballed against.

## Cohorts (#7)

`cohorts.py`'s `group_by_cohort` groups ledger entries strictly on
detection-time information: `entry.detection` (the frozen `SetupCandidate`)
and, when requested, a caller-supplied partition mapping. `entry.latest`
(the lifecycle view) is never consulted — proven by a test that swaps
`latest` for a different candidate and confirms the cohort key is
unchanged. Dimensions available: setup type, direction, symbol, timeframe,
daily/4h/1h structure, RVOL bucket, gap state, confluence counts,
qualification status, primary rejection-check code, and partition.

## Statistics, bootstrap, dependence (#9, #10, #11)

`statistics.py` computes mean/median/stdev/p10/p25/p75/p90 via numpy
percentile linear interpolation, gracefully degrading for n=0/1 rather than
raising. `bootstrap.py` provides percentile-bootstrap confidence intervals
(single-sample and two-sample-difference variants) with a required
deterministic seed, suppressed entirely (not shown as a misleadingly narrow
interval) below `bootstrap_min_sample` (default 20).

`dependence.py` addresses a real statistical hazard directly: overlapping
forward-outcome windows are not independent observations.
`detect_overlap` checks adjacent (by detection time) pairs for
forward-window overlap and always surfaces an explicit
"OVERLAPPING OBSERVATIONS" warning rather than silently running an i.i.d.
bootstrap on dependent data. `block_bootstrap_confidence_interval` offers a
day-blocked alternative (resamples whole exchange trading days, not
individual observations) for when overlap is severe.

## Effect sizes and matched baselines (#12, #13, #14)

`effect_size.py` adds difference-of-medians, difference-of-means, Cohen's d
(pooled-stdev standardized effect size), and Cliff's delta — the last
computed via a sorted binary-search count (`np.searchsorted`), not the
naive O(n·m) pairwise matrix, because baseline cohorts can run into the
thousands of bars and an n·m matrix at that scale is a real memory risk.

`baselines.py` adds (B) direction-matched and (C) structure-matched
baselines on top of Phase 7's (A) unconditional and regime-matched
primitives. `BaselineSample` (`app/research/replay.py`) gained two new
fields, `daily_trend`/`four_hour_trend`, populated from structure replay was
already computing at every step — a small, additive, backward-compatible
change (re-verified against the full anti-lookahead suite after adding it).
`observed_excess_outcome` is explicitly a difference of two medians —
never called alpha, edge, or probability of success anywhere in code,
comments, or the UI.

## Qualification lift and rejection value, expanded (#15, #16)

Both build on Phase 7's existing `qualification_lift`/`rejection_value`
(`app/research/summary.py`) via one shared primitive,
`comparison.py::compare_groups`, which adds sample counts, mean, effect
size, Cliff's delta, MFE/MAE median difference, a two-sample bootstrap
interval, baseline-adjusted excess (when a baseline is supplied), and a
dev/val/test partition breakdown. `rejection_value.py` keeps Phase 7's
multi-bucket convention (an entry failing several hard checks is counted
under every one of those rejection codes).

## Signal decay (#18)

`decay.py` reports distribution + bootstrap interval at each of the
standard horizons (1/3/5/10/20 bars), then classifies the overall shape
with one deterministic label: immediate / delayed / persistent / decaying /
inconclusive. The classification is a simple, fully documented
threshold rule over (earliest horizon's magnitude / peak magnitude) and
(latest horizon's magnitude / peak magnitude) — never a fitted or learned
rule, and never called "predictive confidence." Priority order matters: a
magnitude fade below `decay_delayed_threshold` of peak is checked for
DECAYING *before* IMMEDIATE, otherwise a signal that peaks at the earliest
horizon and then fades away entirely would be misread as merely
"immediate" — this ordering bug was caught by a hand-calculated test before
being fixed.

## Excursion and first-hit path analysis (#19, #20)

`excursions.py::excursion_profile` turns Phase 7's per-entry single-value
MFE/MAE into cohort distributions. `first_hit_analysis` answers a different
question a single MFE/MAE value can't: for two independently configurable
ATR thresholds, which was reached first, walking the same forward-candle
path `app.research.outcomes` already knows how to build
(`forward_candles`/`directional_delta`, both promoted to public for reuse).
When both thresholds are crossed within the same bar, OHLC data alone
cannot order intra-bar events — the deliberate, documented convention is to
assume the worse outcome (adverse-first), the standard conservative
choice when this ambiguity is unresolvable. Explicitly not a stop or target.

## Temporal and cross-symbol stability, concentration (#21-#24)

`stability.py` buckets by calendar month or quarter (`temporal_stability`)
and classifies STABLE/UNSTABLE/INSUFFICIENT_DATA by whether the median's
sign is consistent across buckets with a usable sample —
`cross_symbol_stability` always returns pooled *and* per-symbol results
together, with counts of symbols positive/negative and the stdev of
per-symbol medians as a plain dispersion measure. `concentration.py` flags
when one symbol, one calendar month, or one RVOL-bucket volatility regime
accounts for more than `concentration_warning_share` (default 50%) of a
cohort's samples. "Episode" concentration (a fourth dimension the original
spec named) was deliberately not implemented as its own measure — there is
no clean, generic definition of "one episode" at ledger-entry granularity
that doesn't just re-derive temporal concentration under a different name;
documenting that as unmeasured was judged better than an ad hoc heuristic.

## Historical Analog Engine (#25-#28)

`analogs.py` is split into three strictly separate stages specifically to
make the anti-leakage guarantee structural, not just tested-for:

1. `extract_features` — `SetupCandidate` + the detection candle's own close
   → `AnalogFeatures`. Categorical dimensions come from `SetupFingerprint`
   (setup type, direction, daily/4h/1h structure, RVOL bucket, gap state);
   numeric dimensions are derived from `SetupContext` and the detection
   close (distance to nearest support/resistance in percent, EMA20-relative
   percent, position within the active range) — all detection-time-only.
2. `distance_between`/`rank_analogs` — pure functions of two
   `AnalogFeatures`. Categorical mismatch contributes its full centralized
   weight; numeric mismatch contributes `min(|Δ|/scale, 1.0) × weight`
   (scale differs by dimension: percent-distance dimensions, confluence
   counts, and range position each have their own normalization constant).
   A missing value on either side excludes that dimension entirely from
   both the numerator and the denominator (never treated as a match, never
   NaN) — total distance is `Σcontribution / Σweight-of-compared-dimensions`,
   always in [0, ~1] regardless of how many dimensions were comparable.
   Ties break on `setup_id` for reproducible ordering. Neither function ever
   imports `SetupOutcome`.
3. `attach_outcomes` — a strictly separate decoration pass, run only after
   ranking, that fills in 1/5/10-bar returns and MFE/MAE for
   already-ranked results without ever reordering or rescoring them.

The mandatory anti-leakage test constructs two identical-features cases,
attaches wildly different (fabricated) future outcomes to each, and asserts
the ranking and every distance value is byte-identical before and after —
true by construction given the architecture above, and directly verified.
"Similarity Distance: 0.18"-style output is always accompanied by the full
itemized breakdown (`matched_dimensions`/`differing_dimensions`/
`missing_dimensions`/per-dimension contribution); an unexplained
"X% similar" figure is never produced.

## Research Evidence Cards and quality flags (#29, #30)

`ResearchEvidenceCard` is the one standardized representation: sample
count/label, median, matched baseline, observed excess, bootstrap interval,
partition medians, symbols-positive count — never collapsed into a score.
`EvidenceQualityFlag` is a fixed nine-value enum
(INSUFFICIENT_SAMPLE/SMALL_SAMPLE/OVERLAPPING_OBSERVATIONS/
SYMBOL_CONCENTRATION/TEMPORAL_CONCENTRATION/OUT_OF_SAMPLE_REVERSAL/
DATA_LIMITATION/RESULT_UNSTABLE/MULTIPLE_COMPARISON_WARNING), each computed
from an explicit, already-computed report (`evidence_flags.py`) — nothing
subjective, and every flag that legitimately applies to a weak cohort does
apply (verified with a "genuinely weak cohort" test asserting all six
applicable flags fire together).

## Research contradictions (#17)

`contradictions.py` checks four predefined product assumptions (higher-
timeframe alignment helps; RVOL confirmation helps; S/R confluence helps;
qualification improves breakout_retest behavior) via the same
`compare_groups` primitive #15/#16 use, never a bespoke comparison. Finding
a contradiction only produces a `ContradictionResult` with status
`ASSUMPTION_NOT_SUPPORTED_IN_THIS_SAMPLE` — it never modifies detector
rules. No automatic feature mining exists anywhere in this phase: cohort
dimensions and assumptions are predefined or explicitly caller-selected,
never searched, and `MULTIPLE_COMPARISON_WARNING` fires when a view
displays many simultaneous comparisons (#32/#33).

## Research snapshots and comparison (#34, #35)

`ResearchSnapshotRecord` (migration `0003_research_snapshots`, same
dialect-agnostic `op.create_table` convention as `0002`) is a new,
append-only table: label, source run IDs, config hash, dataset manifest,
cohort definition, filters, statistical output, and warning flags, with no
update path in the repository — a changed conclusion is always a new row,
so an old snapshot stays inspectable even after detector logic changes
later. `compare_snapshots` never silently merges two snapshots; it reports
`same_config_hash`/`same_dataset` up front plus an itemized field-by-field
diff, so "same rules, different period" is never confused with "same
period, different rules."

## API and Research Lab UI

New routes under `/api/research` (`app/api/routes/research_intelligence.py`):
`POST /universe-replay` (runs Phase 7's existing single-symbol
`execute_research_run` once per universe symbol — never a parallel
multi-symbol detection pipeline; cross-symbol research pools the resulting
ledger entries at query time instead), `POST /query` (the consolidated
evidence-card/decay/excursion/stability/concentration/contradictions/overlap
bundle), `POST /analogs`, and the snapshot CRUD + compare endpoints. The
`/research` page keeps Phase 7's working replay UI unchanged and adds
Dataset (multi-symbol universe + partition info), Setup Research filters,
a full Results panel, and a Historical Analogs section with an
expand-to-see matched/differed/afterward view — verified against real,
live yfinance data end to end (see completion report for the concrete
run: 357 bars, 254 qualified/72 rejected setups, a real
`ASSUMPTION_NOT_SUPPORTED_IN_THIS_SAMPLE` contradiction finding, and a
working analog search with correct nearest-neighbor ordering).

## Replay performance: profiled, not optimized

Phase 7 measured ~37s wall-clock for ~340 replay bars through the browser;
this phase re-measured it live (357 bars, 37.5s) and then profiled the
deterministic pipeline in isolation, offline, against the real static SPY
fixture (250 bars, `cProfile`, no network variance):

- `run_replay` total: **3.73s for 250 bars (14.9ms/bar)**, 16.9M function
  calls.
- Breakdown by cumulative time: **Setup Detection 1.53s (41%)**,
  **Market Structure Engine 1.34s (36%, called 750× — 3 timeframes ×
  250 bars)**, **Support/Resistance Engine 0.58s (15%)**, Feature Engine
  0.22s (6%), outcome evaluation for all 260 ledger entries **0.037s (~1%)**.
- Largest internal-time (tottime) hotspots: a generator expression in
  `setup_detection/detectors/_common.py:142` (3.16M calls, 0.48s),
  `sorted()` (57K calls, 0.23s), `exchange_trading_date`/`astimezone`
  (over 1M calls combined, ~0.35s+0.19s).

Conclusion: **the deterministic pipeline is not the bottleneck.** At
14.9ms/bar, 357 bars is ~5.3s of compute — the other ~32s of the measured
37.5s wall-clock time is network I/O (three separate `provider.get_candles`
calls per replay: primary/daily/4h) and SQLite persistence, neither of
which "safe" code optimization of the detection pipeline can meaningfully
improve.

One plausible optimization was seriously considered and deliberately
**not** implemented: caching the daily/4h `MarketStructureSnapshot`
across consecutive replay steps within the same trading day (`daily_window`
and `four_hour_window` are frequently identical bar-for-bar across many
consecutive 1H steps, since a new daily bar only appears once per day).
It was rejected because `compute_market_structure_snapshot` re-truncates
its input by `as_of` internally (`truncate_to_as_of` +
`completed_only`/`candle_complete_at`), and replay's own window-slicing
(`_index_at_or_before`, keyed on raw `timestamp`) does not provably use the
identical boundary semantics as `completed_only` (keyed on
`candle_complete_at`, which folds in session-close time) — a cache keyed
on "same window" without also proving these two truncation rules agree at
every boundary would risk silently reusing a snapshot from a subtly wrong
`as_of`, exactly the class of bug item #41 warns against. The potential
saving (at most the 1.34s Market Structure share, ~36% of a 3.73s
compute budget that is itself only ~14% of total wall-clock time) does not
justify that risk. No optimization was implemented; no performance parity
tests were needed because nothing changed. This conclusion — profile
first, and don't optimize when the dominant cost is uncontrollable I/O and
the one real optimization candidate carries correctness risk — is itself
the outcome item #40-42 asked for.

## Known limitations

- Cross-symbol/universe research is built from N independent single-symbol
  replay runs pooled at query time, not a native multi-symbol replay
  engine — acceptable because every research_intelligence function already
  operates on a flat, symbol-tagged `list[SetupLedgerEntry]` regardless of
  provenance, but it does mean a "universe run" has no single run_id of its
  own, only a set of per-symbol run_ids.
- "Episode" sample-concentration (as opposed to symbol/month/volatility
  regime) is not implemented; see the concentration section above.
- True ATR-normalized-volatility-regime is not a separate analog dimension;
  `rvol_bucket` (categorical) is used as the volatility-adjacent signal
  instead, since a clean cross-symbol ATR/price normalization needs
  plumbing this phase didn't build.
- The historical analog corpus is built from whatever `run_ids` the caller
  supplies; there is no persisted, pre-indexed analog corpus, so a large
  corpus means fetching candles for every distinct symbol in it at query
  time.
