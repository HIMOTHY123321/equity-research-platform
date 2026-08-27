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

## Status

In progress. Remaining Phase 9 work (Research Lab UI for independence/
walk-forward/conclusion-stability/analog-diversity, a small dashboard
overlap-warning pill, historical-data cache and dataset freeze, the full
universe re-run under Phase 9 methodology, and the RANKING GATE decision)
will be appended to this ADR as it lands, the same way ADR 0010 accumulated
sections through Phase 8.
