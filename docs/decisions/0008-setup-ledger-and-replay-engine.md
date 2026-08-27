# ADR 0008: Setup ledger, historical replay, and outcome research (Phase 7)

## Core principle: two information domains that must never touch

Detection-time information (what the deterministic pipeline knew at
timestamp T) and evaluation-time information (what price did afterward)
live in structurally separate places. `app.setup_detection` never imports
anything from `app.research`; `SetupCandidate` (Phase 6's frozen detection
payload) and `SetupOutcome` (`app/research/schemas.py`) are different
top-level pydantic models with no shared fields. `evaluate_setup_outcome`
(`app/research/outcomes.py`) is the *only* function in the codebase allowed
to inspect candles after a setup's own `candidate_candle_timestamp` — every
other engine (features, structure, S/R, setup detection) is forbidden from
seeing anything past `as_of` by construction. The module boundary is the
architecture's enforcement mechanism, not a comment.

## Replay semantics

`app/research/replay.py::run_replay` walks completed primary-timeframe bars
forward one at a time. At each step T:

1. `as_of = candle_complete_at(candle)` — the exact instant T's own bar
   finishes, matching how the live `/setups` endpoint treats "now".
2. A **bounded trailing window** ending at T is sliced from the
   already-fetched candle series (`ResearchConfig.candle_window_by_timeframe`,
   a deliberate standalone copy of `CANDLE_LIMIT_BY_TIMEFRAME` from
   `api/routes/market.py` — see "Live/replay parity" below for why this
   isn't an import).
3. The **exact same** `compute_feature_snapshot` /
   `compute_market_structure_snapshot` / `compute_support_resistance_snapshot`
   / `compute_setup_detection_snapshot` calls the live route makes are
   called again here, unmodified, with that window and that `as_of`.
4. Every candidate in the resulting snapshot is diffed against previously
   seen setup ids; new ids open a ledger entry, known ids get their
   lifecycle view updated (never their frozen detection payload).
5. Advance to T+1.

Nothing is ever precomputed across the full history and sliced afterward.
This is deliberate: item #32 of the Phase 7 spec is explicit that
"calculate all swings across full history first, then loop" is a lookahead
risk, and the two real bugs found this phase (see below) were only visible
*because* replay walks forward sequentially rather than computing once.

## Live/replay parity

If a live `/setups` call and a replay step land on the same `as_of`, they
must produce the same snapshot. This is true by construction, not by
testing effort, because both code paths call the identical `compute_*`
functions with identically-bounded windows — replay is never a second
implementation of detection logic. `ResearchConfig.candle_window_by_timeframe`
duplicates `CANDLE_LIMIT_BY_TIMEFRAME`'s values rather than importing them
specifically so `app.research` has zero dependency on `app.api` (keeping
the layering one-directional: api → research → setup_detection → ...,
never the reverse) — the values must be kept in sync by hand, which is
checked by `test_1_replay_detection_at_t_equals_normal_detector_snapshot_at_t`
in `tests/unit/research/test_anti_lookahead.py`, run against real SPY data.

## Setup ledger

`SetupLedgerEntry` (`app/research/schemas.py`) wraps a `SetupCandidate`
rather than reinventing its fields: `detection` is written once, at first
observation, by `ledger.py::new_ledger_entry`, and is **never** touched
again. `current_state`/`last_observed_at`/`latest` are the only mutable
view, updated by `ledger.py::with_updated_lifecycle` — which returns a new
frozen pydantic instance via `model_copy`, never mutates in place. A setup
that starts as a `wick_failed_breakout` candidate and later (on a
completely different detector's evaluation) becomes relevant again keeps
its original `detection` forever; only `latest`/`current_state` move.

## Immutable detection context

`SetupCandidate.context` (Phase 6's `SetupContext`) already carries
everything item #6 asks for — ATR, RVOL, gap state, MA relationships,
structure on every relevant timeframe, nearest S/R, active range, evidence,
conflicts, fingerprint — frozen at the exact `as_of` the candidate was
detected at. Phase 7 adds nothing to this; it is reused verbatim as the
ledger's `detection.context`, which is the whole point of not duplicating
Phase 6's schema.

## Configuration hashing & reproducibility

`app/research/config_hash.py::build_config_snapshot` collects every
dataclass config that can change what a run detects/qualifies/measures —
`FeatureConfig`, `MarketStructureConfig`, `SupportResistanceConfig`,
`SetupDetectionConfig`, `ResearchConfig` — into one plain dict, stored
verbatim on `ResearchRun.config_snapshot`. `compute_config_hash` SHA-256s a
canonical (sorted-keys) JSON serialization of that dict, truncated to 32
hex characters, stored as `ResearchRun.config_hash`. Two runs with the same
hash used byte-identical rules; a changed threshold anywhere in the
pipeline changes the hash. `test_9_config_hash_stable_for_identical_configuration`
proves both directions: identical config -> identical hash, one changed
field -> different hash.

## Dataset provenance

`app/research/provenance.py::build_dataset_provenance` records provider
name, symbol, timeframe, requested vs. actual candle range, candle count,
adjustment mode, timezone, and a SHA-256 hash of the full OHLCV series
actually used. This exists because yfinance is explicitly not guaranteed
immutable (ADR 0006) — if a later re-run of the same symbol/range/config
produces a different `data_hash`, that's the signal the underlying data
changed, not the code.

## Outcome definitions

- **Forward return** (`outcomes.py::compute_horizon_outcomes`): at each
  configured horizon (default 1/3/5/10/20 bars), `future_close`,
  `absolute_change`, and `raw_return_percent` relative to the detection
  candle's own close (`base_price`). A horizon with fewer than that many
  future completed bars available is `available=False` with every value
  `None` — never fabricated (verified by
  `test_horizon_unavailable_when_insufficient_future_bars`).
- **Directional return**: `raw_return_percent` for a bullish setup;
  `-raw_return_percent` for bearish, so a favorable outcome is always
  positive regardless of direction, and the raw value is preserved
  alongside it (never discarded).
- **MFE/MAE** (`compute_excursion`): MFE reads the *high* for a bullish
  setup / *low* for bearish (the best price could have offered before the
  close); MAE reads the opposite extreme. Both are expressed in the same
  directionally-adjusted convention as `directional_return` — MFE is always
  `>= 0`, MAE is always `<= 0`. `atr` divides the same directional delta by
  `context.atr`, the ATR *frozen at detection*, never recomputed from later
  data (`test_6_atr_normalized_outcomes_use_atr_frozen_at_detection`).
- **Structural events**: two deliberately small, objective labels —
  `reference_level_retested` and `active_range_opposite_boundary_reached`
  — both derived purely from fields already on the frozen candidate. No
  trading targets, no stops, no profit levels anywhere in this module.

All outcome math was hand-verified against fixtures with known expected
values before being trusted against real data — see
`tests/unit/research/test_outcomes.py`.

## Rejected-candidate research

Every rejected `SetupLedgerEntry` gets exactly the same `SetupOutcome`
treatment as a qualified one (`engine.py` evaluates outcomes for the whole
ledger, not just qualified entries). `summary.py::rejection_value` groups
rejected entries by which specific `hard_checks` code failed and compares
that group's median 5-bar directional return against the same setup type's
qualified median — descriptive only, explicitly not a causal claim (the
Phase 7 spec's own wording, "observed historical difference," is used
verbatim in both the API schema docstrings and the UI).

## Baselines

`baseline.py` computes two control groups, collected as a byproduct of
replay's own step loop (no second pass): an **unconditional** baseline
(plain forward returns for every bar in the window, regardless of any
setup) and a **regime-matched** baseline (the same, restricted to bars
where the primary-timeframe trend matched the setup's own dominant
direction). Both stay purely descriptive per the "do not over-engineer
statistical matching" instruction — no propensity matching, no controls
beyond the one trend bucket.

## Sample-size labels

`summary.py::sample_size_label` buckets every group's `n` into
`INSUFFICIENT_SAMPLE` (<20) / `SMALL_SAMPLE` (20-49) / `MODERATE_SAMPLE`
(50-199) / `LARGER_SAMPLE` (200+) — descriptive only, attached to every
`GroupOutcomeStats` and `RejectionValueEntry` the API returns, and rendered
directly in the Research Lab UI next to every sample count so a small
sample is never presented as if it were meaningful evidence.

## Persistence

Phase 1 already defines a database schema (`app/database/models.py`,
`alembic/versions/0001_initial_schema.py`) with tables like
`detected_setups` (a bare `detected: bool`) and `predictions`
(`score`/`entry`/`target_1..3`/`risk_reward_ratio`). Phase 7 does **not**
build on these, for two independent reasons:

1. **Semantic mismatch.** Phase 6's `SetupCandidate` is a structured
   evidence tree, not a boolean; Phase 7 is explicitly forbidden from
   scoring, entries, targets, or P&L (#51-#53). Shoehorning either into the
   Phase 1 schema would mean adding a large number of always-null columns
   to tables designed for a different, not-yet-built product shape.
2. **Dialect mismatch.** The Phase 1 tables use Postgres-only types
   (`postgresql.UUID`, `CREATE EXTENSION "uuid-ossp"`) and were never
   actually wired into any running code path through Phases 2-6 (watchlist
   uses an in-memory repository; nothing else touches the database). Per
   the explicit instruction not to hack migrations to force
   Postgres-specific tables onto SQLite, they're left exactly as they are.

Three new tables (`research_runs`, `setup_ledger_entries`, `setup_outcomes`)
use SQLAlchemy 2.0's dialect-agnostic `Uuid` type (native UUID on Postgres,
CHAR(32) hex on SQLite) instead of the Postgres-only helper. `DATABASE_URL`
now defaults to a local SQLite file (`app/config.py`) so Phase 7 works with
zero setup — no paid service, no local Postgres install. A new Alembic
migration (`0002_research_tables.py`) uses `op.create_table` (dialect-
agnostic) rather than 0001's hand-authored raw Postgres SQL, so it applies
cleanly to a real Postgres deployment where both 0001 and 0002 run in
sequence. For local SQLite development specifically —where replaying 0001
would fail outright on `CREATE EXTENSION` and Postgres-only column types —
`SqlAlchemyResearchRepository.__init__` bootstraps just the three Phase 7
tables directly via `Base.metadata.create_all(..., checkfirst=True)`. This
is not a migration hack: it never touches or depends on the Phase 1 tables,
is a no-op against an already-Alembic-provisioned Postgres database, and
Alembic remains the single source of truth for anyone deploying to Postgres.

`ResearchRun.summary` stores the fully-computed `ResearchRunSummary` as
JSON, computed once at run completion while candles/outcomes are still in
memory, rather than recomputed from raw candles on every summary request.

## Anti-lookahead guarantees

The 13 mandatory invariants (Phase 7 spec #47) are implemented as 11 test
functions in `tests/unit/research/test_anti_lookahead.py` (some invariants
naturally share one test), run against real SPY data captured offline —
see that file for the full mapping. Two real bugs were found enforcing
them, both in Phase 6 detectors that had never been exercised by *repeated*
sequential evaluation before Phase 7's replay existed:

### Bug: `gap_continuation` re-detected the same gap every hour

`gap_continuation.py` anchored its `candidate_candle_timestamp` to
`inputs.candles[-1]` — "whichever bar is latest right now." A live
single-snapshot query never notices this, since it only ever asks "what's
true right now." Replay calls the same detector once per historical bar,
and a gap that holds for an entire trading day was producing a brand-new
candidate on every one of that day's hourly bars — a duplicate-signal bug
(the general principle Phase 6 spec #26 already required) that was
structurally invisible until something called the detector repeatedly.
Fixed by anchoring to the session-open bar instead (matching `gap_fill.py`'s
existing convention), so every bar of the same gapped day resolves to the
same deterministic id and updates one ledger entry's lifecycle instead of
minting new ones.

### Known limitation, deliberately not rushed: `trend_pullback`

The same class of bug exists in `trend_pullback.py` (confirmed on real
data: the same invalidation swing produced ~7 near-duplicate candidates
across 7 consecutive hourly bars) but was **not** fixed this phase. The
natural fix — anchor `candidate_candle_timestamp` to the invalidation
swing's own `confirmed_at` instead of "latest" — was implemented and then
reverted, because `compute_expires_at` derives a candidate's expiration
window from that same timestamp, and a swing confirmed many bars in the
past would make a *brand-new* candidate born already past its own
expiration. Fixing this properly needs `build_resolved_candidate` to accept
separate identity and expiration-anchor timestamps, which is a Phase 6
API change, not a Phase 7 one — left for a follow-up rather than rushed
under time pressure with a real risk of introducing a worse regression.
`trend_pullback` samples in Phase 7 research output should be read with
this in mind: `n` is inflated relative to genuinely independent pullback
events.

## Worked example (chronological)

Real SPY 1H data, `previous_day_low_breakdown`:

```
2026-08-10 11:30  Confirmed close below previous-day low (94.20) --
                   candidate created AND qualified at this same instant
                   (single-transition detector: detection and confirmation
                   coincide). SetupLedgerEntry opened, `detection` frozen.
2026-08-10 12:30  Replay's next step: this same setup_id still appears in
                   the live snapshot (within its lookback/expiration
                   window) -- `with_updated_lifecycle` updates `latest`,
                   `detection` untouched.
2026-08-11 07:30  No confirmation event further changed the candidate's
                   state before its configured expiration window elapsed --
                   `engine.py::_apply_expiration` (Phase 6, reused
                   unmodified) marks it EXPIRED at this instant, appended
                   as a new transition, never backdated to 08-10.
...replay finishes walking the full requested window...
Outcome evaluation (app/research/engine.py, after replay): scans every
                   candle AFTER 2026-08-10 11:30 (the frozen
                   candidate_candle_timestamp) -- and ONLY those -- to
                   compute 1/3/5/10/20-bar forward returns, MFE, MAE, using
                   ATR=4.40 (frozen in `detection.context.atr` at
                   2026-08-10 11:30, never recomputed).
```

## What's honestly out of scope / simplified this phase

- `trend_pullback`'s duplicate-signal limitation (above) — real, disclosed,
  deliberately not rushed.
- MFE/MAE search the *entire* available future candle series (however much
  was fetched), not a bounded window — this is spec-correct (#11/#12 don't
  cap the search range) but is part of why replay runtime scales with how
  much future data is fetched; see the completion report's performance
  section for measured numbers and the tradeoff this implies.
- Structural events (#15) are intentionally limited to two objective
  labels rather than the full list of examples the spec mentions
  (breakout-level retest, active-range boundary) -- "only implement events
  that can be defined objectively from existing deterministic data" was
  taken literally rather than as a request to build every example listed.
- Regime-matched baselines use one bucket (the setup's own dominant
  direction) rather than more granular regime matching, per the explicit
  "do not over-engineer" instruction.
