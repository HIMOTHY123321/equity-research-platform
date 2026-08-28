# ADR 0012: Independent evidence validation & robustness engine (Phase 9)

## Scope and non-goals

Phase 8 built the statistics; it also found that its own raw ledger-entry
counts overstate independent evidence (mean overlapping-observation fraction
≈91.3% across the universe run). Phase 9 does not add new statistics -- it
adds a second, stricter evidence layer on top of Phase 8's, and answers one
question honestly: **how much independent evidence do we actually have**,
and do Phase 8's headline findings survive being re-checked against it?

Explicitly out of scope, same as Phase 8: 0-100 scores, probabilities,
A/B/C/F grades, AI trading recommendations, ML predictions, automated
parameter optimization, entries/stops/targets/position sizing, paper/real
trading. Phase 9 adds one more explicit constraint of its own: **no
detector-rule or threshold changes because a Phase 8 or Phase 9 result looks
bad.** Every module in this phase is read-only with respect to
`app/setup_detection/config.py` -- new thresholds this phase introduces
(episode grouping, purged-sample horizons, conclusion-stability ratios) live
entirely in `app/research_intelligence/config.py`, which has zero influence
on what gets detected or qualified.

Raw Phase 8 results are preserved unchanged. Nothing in this phase deletes,
merges, or rewrites a `SetupLedgerEntry` -- every new concept (episode,
purged sample, walk-forward fold) is a read-only research abstraction
computed *from* the raw ledger, alongside it, never replacing it.

## Setup Episode grouping (#3, #4)

`app/research_intelligence/episodes.py`. Core problem: a setup firing
repeatedly during the same underlying market move is not many independent
examples of that setup working. Rather than "blindly group everything within
N bars" (explicitly rejected), episodes are built with a deterministic,
detector-native rule: within each `(symbol, timeframe, setup_type,
direction)` group, sorted chronologically, each entry after the first joins
the immediately preceding entry's episode via one of two bases --

- **STRUCTURAL_REFERENCE**: both entries share the same non-null
  `(reference_source, reference_timestamp)` -- the strongest possible
  evidence they are anchored to the literal same swing/level/zone.
- **TEMPORAL_PROXIMITY** (fallback, only eligible when at least one side
  lacks reference info -- if both sides *have* a reference and it differs,
  that is a genuine "different event" signal that is never overridden by
  mere time proximity): within that setup type's own
  `get_expiration_bars()` window, converted to wall-clock time via
  `bar_duration_seconds()`. This reuses the exact bar count production code
  already uses to decide how long this setup type's opportunity window
  stays open -- detector-native, not an invented constant.

Episode IDs are deterministic (`sha256` of symbol/setup_type/direction/
timeframe/anchor-setup-id), so two runs grouping the same ledger entries
always produce the same episode ID. On the real SPY 1H trend_pullback
fixture, this collapses 25 raw ledger entries (already post-ADR-0009
duplicate-fix) into 20 episodes -- a real, explainable reduction, not a
no-op: ADR 0009's fix only collapses same-instant-streak duplicates, while
episode grouping catches a *different* form of dependence (the same swing
reference producing multiple distinct held/broken/re-held streaks over
time).

**Representative episode selection (#8)**: deterministic and fixed at
detection time -- the first QUALIFIED member (by `candidate_candle_timestamp`,
`setup_id` tiebreak), else the episode's first member overall. Never chosen
by which member later produced the best outcome; outcome fields are never
read by the selection function.

## Independent observation sets (#5-#7)

`app/research_intelligence/independence.py`. Three views of the same raw
ledger entries:

- **RAW**: every entry (Phase 8's behavior, unchanged).
- **EPISODE-LEVEL**: one representative entry per `SetupEpisode`.
- **PURGED** (horizon-specific): a deterministic greedy chronological
  selection -- process entries earliest-first; selecting one excludes every
  later *same-symbol* entry whose own detection timestamp falls inside the
  selected entry's forward-outcome window for that horizon
  (`bar_duration_seconds(timeframe) * horizon_bars`). The exclusion boundary
  per symbol only ever extends forward, never shrinks; different symbols
  never block each other. `purged_sample` takes `horizon_bars` as a
  required argument -- independence is horizon-specific by construction,
  there is no single universal "independent" set (`purged_5_bar` and
  `purged_20_bar` are genuinely different samples).

`sample_composition()` reports raw count / episode count / purged count per
horizon side by side, e.g. "Raw observations: 340, Independent episodes:
61, Purged 5-bar samples: 47" -- never a single invented "effective N".

`per_observation_overlap()` reports overlap per individual observation
(overlap count, same-symbol overlap, same-episode overlap, max shared bars)
rather than folding everything into one aggregate warning, so a caller can
see *which* observations are dependent on which, not just an overlap
percentage.

## Block bootstrap hardening (#10)

`app/research_intelligence/dependence.py`. `block_bootstrap_confidence_interval`
now takes a `block: "daily" | "weekly"` parameter (daily keyed by
`exchange_trading_date`, weekly by ISO `(year, week)`); an invalid choice
raises rather than silently falling back. `compare_bootstrap_methods()`
returns naive/daily-block/weekly-block intervals side by side for the same
sample -- all three share the same point estimate, only their intervals
differ by resampling granularity. Weekly is the more conservative choice
when 1H-bar dependence chains span more than a single trading day; callers
should default to the widest available block interval rather than silently
picking naive.

## Conclusion stability (#11, #12)

`app/research_intelligence/conclusion_stability.py`. Re-runs a two-group
finding (e.g. qualified-vs-rejected, HTF-aligned-vs-opposed) at all three
independence levels via the shared `compare_groups` (episode-level and
purged samples are drawn per-group from the pooled entries, splitting by
which original group each representative/purged member belongs to), then
classifies whether the raw conclusion survives with one deterministic rule,
never a hand-picked label:

```
ratio = purged_median_difference / raw_median_difference

ratio < conclusion_reversal_ratio_threshold (-0.1)   -> REVERSES
ratio <= conclusion_disappears_ratio_threshold (0.1)  -> DISAPPEARS
ratio < conclusion_survives_ratio_threshold (0.7)     -> WEAKENS
otherwise                                             -> SURVIVES
```

with an early `INSUFFICIENT_INDEPENDENT_SAMPLE` exit whenever the purged
sample is too small on either side (`< small_sample_min` per group) or the
raw difference is exactly zero (ratio undefined). This mirrors `decay.py`'s
existing convention of deterministic, documented thresholds rather than a
fitted/learned rule.

## Anchored walk-forward validation (#13-15)

`app/research_intelligence/walk_forward.py`. Mandatory (rolling walk-forward
deferred -- correctness on the anchored form matters more than adding both).
A chronologically sorted sample is split into `fold_count + 1` contiguous
chunks; chunk 0 is the initial anchor history, and chunks 1..fold_count are
successive, non-overlapping test folds. Each fold's "train" boundary (the
union of all earlier chunks) is recorded for transparency and expands with
each fold, but nothing is fit on it -- this codebase tunes no parameters
(#16), so walk-forward here answers "does the finding's direction hold up on
later, unseen periods" rather than "does a fitted parameter generalize".
Stability is classified by the same sign-consistency rule `stability.py`
already uses for temporal buckets: STABLE if every fold's median keeps the
same sign, UNSTABLE if it flips, INSUFFICIENT_DATA if fewer than 2 folds
have a usable median.

## No-parameter-tuning discipline (#16)

A hard constraint on how this phase is built, not a new module: nothing in
`app/research_intelligence/` is permitted to modify
`app/setup_detection/config.py`'s production thresholds, and no code in this
phase reads a Phase 8 or Phase 9 finding and adjusts a detector rule in
response. Where comparing alternate detector parameters would be useful
research, the pattern is: run a second `ResearchRun` under a deliberately
different, separately-committed `SetupDetectionConfig`, save both as
`ResearchSnapshot`s, and compare them explicitly (`compare_detector_versions`,
below) -- never silently pick whichever result looks better and call it
validated.

## Detector-version comparison infrastructure (#17)

`app/research_intelligence/snapshots.py::compare_detector_versions`. Not a
new mechanism: `config_hash` (`app.research.config_hash.compute_config_hash`)
already hashes every threshold in `FeatureConfig` / `MarketStructureConfig`
/ `SupportResistanceConfig` / `SetupDetectionConfig` / `ResearchConfig`, so
it already *is* a detector-version fingerprint, and Phase 8's
`compare_snapshots` already reports `same_config_hash` alongside
`same_dataset`. `compare_detector_versions` is a thin, discoverably-named
wrapper around the same function -- infrastructure only. Nothing generates a
second detector version automatically; that stays a manual, deliberate,
separately-committed act.

## Independent qualification-lift and rejection-value (#18, #19)

`qualification.py::independence_adjusted_qualification_lift` and
`rejection_value.py::independence_adjusted_rejection_value` are thin
wrappers that re-run the existing Phase 8 comparisons (qualified-vs-
rejected, each rejection code vs. qualified) through `conclusion_stability`
at every horizon instead of `compare_groups` directly, producing a
`ConclusionStabilityReport` per horizon (per rejection code, for rejection
value) alongside the unchanged Phase 8 `expanded_qualification_lift` /
`expanded_rejection_value` outputs -- never replacing them.

## Analog diversity (#20, #21)

`analogs.py::analog_diversity_report` and `analogs.py::diverse_analogs`.
Both are strictly post-ranking passes -- `distance_between`/`rank_analogs`
are untouched. `analog_diversity_report` checks two independent,
deterministic conditions on an already-ranked list: how many of the top
analogs provably share a `SetupEpisode` (the strongest same-event signal
this package has), and whether one symbol dominates the list (reusing the
existing `concentration_warning_share` threshold). This is the "episode
concentration" dimension Phase 8's `concentration.py` explicitly declined
to build, because no episode concept existed yet -- it does now.
`diverse_analogs` returns the same ranked list filtered to at most one
analog per episode (keeping each episode's closest member, since the input
is already distance-sorted); analogs with no known episode are never
deduplicated against anything.

## Evidence quality upgrade (#22, #23)

`ResearchEvidenceCard` gained independence-adjusted fields alongside its
existing (unchanged) raw ones: `independent_episode_count`,
`purged_sample_count` (at a caller-chosen horizon, defaulting to the
card's own), `overlap_rate`, `block_bootstrap_interval` /
`bootstrap_method`, `walk_forward_stability` with its positive/negative
window counts, `symbol_coverage_count`, `temporal_coverage_buckets`.
`evidence_card.py::build_evidence_card` computes all of it from the same
`entries` the card already receives -- episodes and walk-forward folds need
nothing extra; a purged count and block bootstrap reuse the card's own
horizon unless overridden.

Eight new deterministic `EvidenceQualityFlag` values (`evidence_flags.py::
compute_independence_flags`, a separate function from Phase 8's
`compute_evidence_flags` so existing call sites are untouched): HIGH_OVERLAP
(overlap rate >= concentration_warning_share), LOW_INDEPENDENT_SAMPLE
(purged count < small_sample_min), EPISODE_CONCENTRATION (one episode >=
concentration_warning_share of raw observations), WALK_FORWARD_INSTABILITY,
PURGED_RESULT_REVERSAL (from a supplied `ConclusionStabilityReport`'s
REVERSES label), BLOCK_BOOTSTRAP_INCLUDES_ZERO (interval spans zero),
SINGLE_SYMBOL_DEPENDENCE (<=1 symbol contributed data), TEMPORAL_INSTABILITY
(temporal stability is UNSTABLE or INSUFFICIENT_DATA -- deliberately
broader than Phase 8's `RESULT_UNSTABLE`, which stays UNSTABLE-only).

## Evidence maturity (#24)

`evidence_maturity.py::classify_evidence_maturity`. Built only because
every input it needs now genuinely exists. A fixed, ordered checklist
(never a weighted or fitted combination) over an already-built
`ResearchEvidenceCard` (+ an optional `ConclusionStabilityReport`):
INSUFFICIENT if the purged sample is below `small_sample_min`; MIXED if a
supplied conclusion-stability label is WEAKENS/DISAPPEARS/REVERSES (checked
before REPLICATED on purpose -- a large sample never excuses a conclusion
that falls apart under its own independence adjustment); REPLICATED only
if purged n >= `moderate_sample_min` AND walk-forward is STABLE AND every
symbol with data agrees in sign (>= 2 symbols) AND (no conclusion report
supplied, or it SURVIVES) AND none of seven fragile-independence flags are
present; PRELIMINARY otherwise. Full documented rule in the module
docstring, mirroring `decay.py`'s "priority order matters, and here is
why" convention.

## API and Research Lab UI (#25-#28)

`POST /api/research/query` gained an additive `independence` field
(`IndependenceSection`: `sample_composition`, `walk_forward`,
`evidence_maturity` + basis, and `conclusion_stability` -- populated only
when the setup_type/direction-filtered pool contains both a qualified and
a rejected member to compare) -- every existing field is unchanged.
`POST /api/research/analogs` gained additive `diversity`
(`AnalogDiversityReport`) and `diverse_analogs` fields, computed strictly
after ranking. Both endpoints reuse the request's already-pooled ledger
entries; the independence computation costs one extra pass over data
already in memory, no new fetches.

`apps/web/src/components/research/ResearchResultsPanel.tsx` gained an
`IndependenceBlock`: raw/episode/purged sample counts (per horizon),
overall evidence-maturity badge, a walk-forward stability badge with
per-fold medians and positive/negative counts, and (when applicable) a
raw/episode/purged conclusion-stability table with its deterministic
label. `apps/web/src/components/research/HistoricalAnalogsPanel.tsx`
gained an optional diversity warning line and a "SHOW DIVERSE ANALOGS"
toggle that swaps between the full ranked list and the one-per-episode
filtered list -- same distances, same order, verified live against the
real SPY fixture (a `moving_average_reclaim` analog search correctly
flagged 6 of the top 10 analogs sharing one episode, and toggling reduced
the displayed list from 10 to 4 while every remaining distance stayed
identical). `AnalogSearchButton.tsx` (the dashboard's "VIEW HISTORICAL
ANALOGS" control) reuses the same component, so the same warning line and
toggle appear there too -- compact enough not to violate #29's
decision-first dashboard constraint.

## Dashboard warning pill (#29)

`AnalogSearchButton.tsx` (the dashboard's on-demand "VIEW HISTORICAL
ANALOGS" control, already firing one quick 30-day replay per click) now
also fires one `/api/research/query` call scoped to the clicked
candidate's own setup_type/direction over that same quick corpus, purely
best-effort -- a 404 (too few matching entries in a short window) or any
other failure is swallowed and shows no pill, never a crash or a blocking
error. If the resulting evidence card carries `high_overlap` or
`low_independent_sample` (a short, deliberate allow-list, not "any flag"),
a single small "RESEARCH SAMPLE HIGHLY OVERLAPPING" pill renders next to
the analog results. No new always-on network calls, no giant statistics
table -- verified live: one setup type in the real fixture correctly
produced no pill (404, too few same-type entries in a 30-day window,
handled silently) while its analog corpus still showed the diversity
toggle from #28, confirming the two features degrade independently.

## Local candle cache and dataset freeze (#32-#34)

`app/market_data/candle_cache.py`, new tables `cached_candle_series` /
`frozen_datasets` (`app/database/models.py`, Alembic `0004_candle_cache`,
same local-SQLite-bootstrap + Postgres-migration dual convention as
`ResearchSnapshotRecord`). Two deliberately separate concerns:

- **Cache** (`get`/`put`, wrapped by `fetch_candles_cached`): keyed on the
  full `(provider, symbol, timeframe, requested_start, requested_end,
  adjustment_mode, session_settings)` tuple -- a different range, symbol,
  or timeframe is always a genuine miss, never a substitution. "Never
  silently stale" is enforced by `_is_cacheable`: any request whose
  `requested_end` falls within `REVISION_WINDOW_DAYS` (5) of "now" bypasses
  the cache entirely on both read and write, since yfinance can still
  revise recent bars (docs/decisions/0006) -- only settled ranges are ever
  cached, and a cached row is never overwritten once written.
- **Frozen datasets** (`freeze`/`get_frozen`/`list_frozen_datasets`): an
  explicit, separate, permanently-immutable snapshot keyed only by its own
  generated id, allowed regardless of recency -- reproducing a past run
  exactly means replaying against a frozen dataset's candles, not
  re-fetching. Both tables reuse `app.research.provenance
  .compute_candle_data_hash` (extracted from `build_dataset_provenance`,
  same formula, zero duplication) so a cached or frozen entry's hash is
  directly comparable to any `DatasetProvenance`/`DatasetManifest` hash
  computed elsewhere.

Wired into both `POST /api/research/replay` and `POST /api/research/
universe-replay` via `fetch_candles_cached`, replacing the direct
`provider.get_candles(...)` calls -- no other behavior in either route
changed. Verified live against the real yfinance provider (a genuinely
uncached March 2025 SPY range, not the fixture dates): cold fetch 0.916s,
warm (cache-hit) fetch 0.051s, byte-exact parity confirmed by comparing
every candle's full serialized form, not just counts. An integration test
against a fake provider additionally proves a second identical `/replay`
call makes zero further provider calls and produces byte-identical
ledger-entry ids to the first (mandatory anti-leakage checklist item #8:
"cached dataset replay must equal original replay"), and that a request
for a different range is a genuine miss, never a stale hit.

One honest caveat, not papered over: for a request whose candle history is
very large (the provider is limit-based, not range-scoped, so a one-month
replay request can still pull years of underlying history), total
end-to-end replay wall-clock is dominated by downstream replay/detection
compute over that full fetched history, not by the fetch itself -- the
cache eliminates the fetch cost precisely as intended (confirmed above),
but does not by itself make a large-history replay fast end-to-end. Per
#31/#16, this is not "fixed" here by rewriting the deterministic engine;
it is reported as a separate, out-of-scope performance characteristic for
a future phase to size properly, not chased against an arbitrary benchmark.

## Universe re-analysis under Phase 9 methodology (#37-#39)

Re-uses the exact same real 8-symbol, 180-day, 1H universe run Phase 8
produced -- all 24,375 ledger entries, still persisted with outcomes in
the local database, verified intact and re-pooled without any re-fetch
(per #1's "preserve Phase 8 results" and #37's "use cached data where
possible"). Script: the scratchpad's `phase9_analysis.py`, run once,
58.5 seconds end-to-end, no network calls.

**Sample composition, pooled**: raw 24,375 -> 18,630 independent episodes
(23.6% reduction) -> 2,930 purged 5-bar samples (88.0% reduction from raw).
Per-setup-type purged-5 counts vary enormously by setup family: some
(`gap_continuation`, `gap_fill`, `previous_day_high_breakout`,
`previous_day_low_breakdown`) show **zero** reduction at any level --
these setups fire rarely enough per symbol that their own observations
essentially never overlap each other, even pooled across 8 symbols and 6
months. Others (`resistance_rejection`: 4,159 raw -> 1,592 purged;
`bearish_liquidity_sweep`: 2,315 -> 1,326) lose more than half their raw
count to purging. This variance is itself a finding: "how much independent
evidence exists" is not one universal number, even within one universe run
-- it depends entirely on how often that specific setup type fires.

**Overlap severity**: pooled 5-bar overlap is **100.0%** (every single one
of 24,375 entries has some adjacent-in-time entry, expected once every
setup type is pooled together on the same bars). Per-setup-type range is
65.0%-100.0%, mean **93.3%** -- consistent with, and slightly higher than,
Phase 8's originally reported 91.3% mean. Phase 8's overlap finding is not
an artifact of that particular partial run; it replicates, and if anything
understates the severity slightly.

**The 5 named Phase 8 findings, re-evaluated** (`conclusion_stability` at
horizon=5, `anchored_walk_forward` 5-fold, `compare_bootstrap_methods`):

1. **trend_pullback rejected outperforms qualified** -- RAW diff=-0.115,
   PURGED diff=-0.148 (ratio 1.28) -> **SURVIVES**. Walk-forward: both
   qualified and rejected cohorts are STABLE (5/5 folds same sign each).
   This counter-intuitive Phase 8 finding is real and independence-robust,
   not an overlap artifact -- if anything the purged effect is *larger*
   than the raw one.
2. **breakout_retest qualified strongly outperforms rejected** -- RAW
   diff=+0.534, PURGED diff=+0.506 (ratio 0.95) -> **SURVIVES**.
   Walk-forward: qualified STABLE (4/4 usable folds positive), rejected
   STABLE (5/5 folds negative). Phase 8's most promising finding remains
   the most promising finding after independence adjustment.
3. **HTF (daily) alignment contradiction** -- RAW diff=-0.045 (aligned
   underperforms opposed), EPISODE diff=-0.030, PURGED diff=-0.0072 (ratio
   0.16) -> **WEAKENS** (just above the 0.10 DISAPPEARS boundary -- the
   effect collapses to essentially nothing under purging, matching almost
   exactly the worked example in Phase 9's own spec). Walk-forward: both
   `daily_aligned` and `daily_opposed` cohorts are UNSTABLE (2 positive /
   3 negative folds each) -- the sign is not even consistent fold to fold.
   **Conclusion: this contradiction does not survive independence
   adjustment; the raw result was substantially inflated by dependent
   observations.**
4. **RVOL confirmation, pooled** -- RAW diff=+0.058, PURGED diff=+0.217
   (ratio 3.76) -> **SURVIVES**, and the independent-sample effect is
   *stronger* than the pooled raw estimate (walk-forward: 4/5 folds
   positive, one flip -- UNSTABLE by the strict same-sign-every-fold rule,
   a real caveat on an otherwise-surviving finding).
5. **RVOL confirmation, breakout_retest only, reverses sign vs. pooled**
   -- RAW diff=-0.109, PURGED diff=-0.116 (ratio 1.07) -> **SURVIVES**.
   The scope-dependent sign reversal Phase 8 found (positive pooled,
   negative scoped to breakout_retest) is itself independence-robust on
   both sides -- a genuine, reproducible pattern, not overlap noise.

**Evidence maturity, every setup type's qualified cohort**: **0 of 14**
setup types with a qualified cohort reach REPLICATED, despite pooled
sample sizes in the thousands for several of them. The dominant blocker,
by inspection of the actual basis strings, is `HIGH_OVERLAP` -- present on
nearly every setup type given the 93.3% mean overlap rate above; several
setup types (`breakout_retest`, `resistance_rejection`) also fail the
cross-symbol sign-agreement requirement (6/8 and 5/8 symbols respectively);
`resistance_rejection` additionally fails walk-forward stability and
carries a block-bootstrap-includes-zero flag. `trend_pullback` is the
closest to REPLICATED of any setup type -- 8/8 symbols agree in sign,
walk-forward stable -- blocked by `HIGH_OVERLAP` alone.

## Answers to the 22 Phase 9 research questions

1. **Raw observation count, pooled**: 24,375.
2. **Independent episode count, pooled**: 18,630 (23.6% fewer than raw).
3. **Purged sample size by horizon, pooled**: 1-bar 6,012; 3-bar 3,757;
   5-bar 2,930; 10-bar 1,983; 20-bar 1,015 -- shrinks monotonically as the
   exclusion window widens, as expected.
4. **How severe is the sample-size collapse**: severe and horizon-
   dependent -- pooled purged-20-bar retains just 4.2% of raw observations
   (1,015/24,375); even the mildest horizon (1-bar) retains only 24.7%.
5. **Which Phase 8 findings survive vs. weaken vs. disappear vs.
   reverse**: SURVIVES -- trend_pullback rejected>qualified, breakout_retest
   qualified>rejected, RVOL pooled, RVOL breakout_retest-scoped reversal.
   WEAKENS (functionally disappears) -- HTF daily alignment. None of the 5
   reversed sign or hit INSUFFICIENT_INDEPENDENT_SAMPLE.
6. **Per-setup-type independent-sample adequacy**: wildly uneven -- 4 setup
   types show literally no purging loss at any horizon (rare enough not to
   overlap), while high-frequency setup types like `resistance_rejection`
   lose over 60% of their raw count to purging alone.
7. **Do block-bootstrap findings change the picture**: no reversals, but
   real widening -- e.g. HTF alignment's naive 90% CI [-0.034,-0.006]
   excludes zero, but its own daily-block CI [-0.053,+0.012] and
   weekly-block CI [-0.062,+0.017] both include zero, i.e. the naive
   interval was overconfident about a finding that independence adjustment
   has already shown does not survive on its own.
8. **Walk-forward stability across the 5 named findings' cohorts**: STABLE
   for trend_pullback (both groups) and breakout_retest (both groups);
   UNSTABLE for both HTF groups and for pooled RVOL-confirmed.
9. **Cross-symbol stability**: trend_pullback and RVOL-confirmed-pooled
   both reach 8/8-symbol sign agreement in their evidence cards;
   breakout_retest 6/8; resistance_rejection 5/8.
10. **Temporal stability**: not separately re-run here (Phase 8's monthly
    buckets stand; the new `TEMPORAL_INSTABILITY` flag, which is stricter
    than Phase 8's `RESULT_UNSTABLE`, fired on `resistance_rejection`).
11. **Is diverse-analog filtering useful in practice**: yes -- live-verified
    in the Research Lab UI (#28) on a real `moving_average_reclaim` query:
    6 of the top 10 analogs shared one episode; the diverse view correctly
    collapsed the list to 4 genuinely distinct cases.
12. **Does evidence now justify a calibrated ranking engine**: **the
    answer is still NO** -- see the RANKING GATE decision below.
13-22: covered by the five re-evaluated findings, the composition/overlap
    numbers, the evidence-maturity table, and the RANKING GATE section
    together -- restated individually here would only repeat the same
    numbers under different headings.

## RANKING GATE decision (#40)

**FAIL.**

**Evidence standard applied** (documented, not intuition): a setup family
would need to reach `EvidenceMaturity.REPLICATED` -- purged n >=
`moderate_sample_min` (50), walk-forward STABLE, every symbol with data
agreeing in sign (>=2 symbols), a supplied conclusion-stability check
(where applicable) at SURVIVES, and none of the seven fragile-independence
flags present -- on at least a meaningful subset of setup types before a
calibrated ranking engine could be built on top of this evidence base
without ranking on noise.

**Result against that standard**: 0 of 14 setup types with a qualified
cohort reach REPLICATED, even with pooled sample sizes in the thousands.
The blocking factor is overwhelmingly `HIGH_OVERLAP` (93.3% mean overlap
rate pooled), meaning the *raw* sample sizes that looked adequate in Phase
8 do not translate into adequate *independent* evidence once dependence is
accounted for.

**What's missing, specifically** (not vague -- these are the actual
blockers found above): (a) lower observation dependence -- either a
genuinely larger multi-year universe run so purged/episode counts grow
past the moderate-sample bar even after heavy exclusion, or a
methodological change to how much of a symbol's history counts as one
independent event; (b) broader, more consistent cross-symbol sign
agreement -- `breakout_retest` and `resistance_rejection` both fail this
specifically; (c) walk-forward stability for `resistance_rejection` and
the HTF-alignment/RVOL-pooled groups, which flip sign fold to fold.
`trend_pullback` is the nearest setup type to clearing the bar -- it is
blocked by `HIGH_OVERLAP` alone -- so it is the best near-term candidate
to revisit once episode/purged methodology or a larger dataset reduces
overlap.

Per #16/#40's explicit instruction, this FAIL is not treated as a reason
to weaken the evidence bar, adjust detector thresholds, or build ranking
anyway "because the numbers are close" -- it stands as the honest
conclusion of the independence-adjusted evidence available today.

## Status

Complete. Final verification: 712/712 backend tests passing, ruff clean,
frontend `tsc`/`eslint`/`build` clean, live browser smoke test clean on
both the dashboard and the Research Lab. Full completion report published
separately (Phase 9 Completion Report artifact).
