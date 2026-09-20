# ADR 0016: Prospective Forward Validation (Phase 12)

## Motivation

Every prior phase answers "what happened historically, and how well did a
rule/setup perform in hindsight?" — Phase 7's replay, Phase 8/9's
research-intelligence statistics, Phase 10's catalyst context, Phase 11's AI
Research Analyst. None of them answer a genuinely different question: "given
only what the platform knew at time T, what did it expect to happen next,
and was that expectation actually right once the outcome became known?"

That question requires a structurally different guarantee than a backtest.
A backtest can always be re-run against the same historical window and
re-checked; a *prospective* forecast is only meaningful if it was locked
**before** the outcome existed and never touched again. Phase 12 builds the
one thing this platform did not yet have: an immutable, timestamped forecast
ledger, a resolver that is the only place future data may enter, and a set
of honest baselines/metrics a real prospective result must beat before
anyone is allowed to claim skill.

**RANKING GATE remains FAIL (ADR 0012) and is untouched by this phase.**
Nothing here produces a score, a rank, a BUY/SELL/STRONG BUY, a price
target, or a probability. This is a validation lab, not a recommendation
engine — see "No ranking / no recommendation policy" below.

## Why a backtest and a prospective forecast are not the same evidence

A backtest (Phase 7 replay, Phase 8/9 research queries) walks forward
through *already-elapsed* history, computing what a rule would have said at
each historical instant. Because the whole dataset already exists when the
backtest runs, there is no way to prove the backtest's own code, its
authors, or its parameter choices were not — even unconsciously — shaped by
already knowing how the story ends. That is not a flaw unique to this
platform; it is the reason backtested edges routinely fail to replicate
going forward across the industry.

A **prospective forecast** is different in one specific, structural way: it
is locked at a real wall-clock instant, before the outcome exists anywhere
in any dataset the system can see, and it is never permitted to change after
that instant. Section "Structural enforcement of never backfilled" below
describes exactly how that is guaranteed rather than merely promised.

Both kinds of evidence are useful; they are never interchangeable, and this
phase never lets one masquerade as the other (see "Historical vs. forward
labeling" below).

## Immutable forecast ledger (`app.forecasting.schemas.ForwardForecast`)

A `ForwardForecast` is a frozen Pydantic model (`model_config =
ConfigDict(frozen=True)`) — an assignment attempt after construction raises
a `ValidationError` at the Python level, not merely a documented convention.
Persistence enforces the same guarantee mechanically:
`SqlAlchemyForecastRepository.save_forecast` looks up the row by
`forecast_id` first and is a no-op if it already exists — there is no
`update_forecast` method anywhere in the repository or its ABC. A second
attempt to "edit" a forecast by saving a different value under the same id
silently keeps the original; correcting a forecast means creating a new,
separately-`forecast_id`'d record, never mutating an old one.

Every forecast carries: `forecast_id`, `created_at`/`market_as_of` (both to
the second, explicit timezone — see "Timestamp semantics"), `symbol`/
`timeframe`, `forecast_category`/`forecast_value`, `forecast_horizon_bars`,
`evidence_packet_id` + `evidence_packet_schema_version` + `pipeline_version`
(binding, below), `evidence_refs`, `evidence_quality` (categorical, never a
score), `origin` (`deterministic_research` or `ai_synthesis`), `status`,
`abstention_reason` when abstained, `rationale`, and `run_mode`
(`prospective` or `backtest_replay`).

## EvidencePacket binding

Every forecast is created against a frozen `EvidencePacket` (Phase 11/11.1's
own point-in-time pipeline, reused verbatim —
`app.ai_analysis.evidence_packet.build_evidence_packet`). The forecast
stores the packet's id, schema version, and pipeline version, and the
packet itself is persisted (`evidence_repository.save_packet`) before the
forecast is. This is the same "no duplicate statistics engine, reuse the
one real pipeline" principle every prior phase has followed — Phase 12 adds
a forecast on top of the evidence, it never re-derives evidence of its own.

## Forecast types (#B) — five closed, machine-evaluable categories

`DIRECTION` (up / down / flat_indeterminate), `STRUCTURE` (support
holds/fails, resistance breaks/rejects, BOS occurs, CHOCH occurs, range
persists/resolves), `VOLATILITY` (expands / contracts), `CATALYST_REACTION`
(persists / fades), `SETUP_OUTCOME` (favorable-before-adverse,
invalidates-before-confirmation, remains-unresolved). Every value lives in
`FORECAST_VALUES_BY_CATEGORY`, a closed `frozenset` per category — this is
the single source of truth both the deterministic engine and the AI-
synthesis path are validated against, and `ForwardForecast`'s own
`model_validator` re-checks membership again at construction time. No
forecast is ever a bare price target or a free-text prediction.

## Two origins, one closed vocabulary

`DETERMINISTIC_RESEARCH` (`app.forecasting.deterministic`) derives a
forecast value from already-computed EvidencePacket fields — a DIRECTION
forecast mirrors a qualified setup's own already-validated directional
thesis, a STRUCTURE forecast targets the nearest support/resistance zone on
that side, VOLATILITY compares current RVOL against a threshold, and so on.
Nothing here re-derives a statistic Phase 3-9 didn't already compute.

`AI_SYNTHESIS` (`app.forecasting.ai_forecast`) is deliberately minimal: a
narrow `ForecastSelectionProvider` ABC (kept separate from
`app.ai_analysis.provider.AIAnalysisProvider` to avoid a layering
inversion — forecasting builds on `ai_analysis`, not the reverse) selects
among the *same* closed per-category value set. Nothing a provider returns
is trusted directly: `select_ai_forecast` independently re-validates the
returned value against `FORECAST_VALUES_BY_CATEGORY`, requires every cited
evidence ref to resolve within the caller's own `EvidenceClaim` list, and
screens the rationale against `app.ai_analysis.validation._BANNED_PATTERNS`
(reused verbatim — including a new `confidence_claim` pattern this phase
added for "NN% confident", closing the same gap "NN% chance" was already
closed for). Any failure — an invented value, an unresolvable ref, banned
language, or the provider being unavailable — abstains with
`PROVIDER_LIMITATION`; it never partially accepts or patches a bad
response.

## Abstention is a first-class outcome (#C)

A forecast can honestly say "no forecast" with a specific reason from a
fixed vocabulary (`AbstentionReason`): too few purged episodes, high
overlap, unstable evidence, contradictory research, insufficient historical
analogs, stale data, provider limitation, catalyst ambiguity, or ranking-
gate restriction. Abstention and a real forecast are the *same record type*
(`ForwardForecast.status` distinguishes them), so abstention rate is always
computed from the same ledger the forecasts themselves live in — there is
no separate, easy-to-forget "abstentions" table that could silently drift
out of sync. `_insufficiency_reason` picks the most specific applicable
reason in a fixed priority order, never a generic catch-all when a more
specific one applies.

## No probabilities (#E)

"72% chance", "90% confident", a win-rate percentage, a confidence score —
none of these are permitted anywhere a forecast's rationale or an AI
provider's output is validated (`_BANNED_PATTERNS`, reused from Phase 11).
The only quality signal exposed is `EvidenceQualityState` — `HIGH_EVIDENCE_
SUPPORT` / `MIXED_EVIDENCE` / `WEAK_EVIDENCE` / `INSUFFICIENT_EVIDENCE` — a
categorical classification derived deterministically from already-computed
Phase 8/9 fields (evidence maturity, conclusion stability, overlap,
concentration warnings; see `app.forecasting.evidence_quality`), never a
number. This restriction is explicit and deliberate: no probability claim
is credible until this system has actually demonstrated prospective
calibration, which by definition cannot happen before real prospective
results exist.

## Outcome separation — the resolver is the only door for future data (#G)

`app.forecasting.resolver.resolve_forecast` is the single place a
`ForecastOutcome` is produced, and the single place any function in this
package is allowed to look at data timestamped after `market_as_of` — the
same "one place allowed to look at candles after the fact" discipline
`app.research.outcomes` already established for Phase 7/8 (ADR 0008),
applied to a new object. It never mutates the `ForwardForecast` it
resolves; it always produces a brand-new, separate row linked by
`forecast_id`. A forecast and its (at most one) outcome are two different
persisted records, on purpose — "what we predicted" and "what actually
happened" must never be collapsible into a single mutable row.

Horizons are counted in real bars (`forward_candles`, reused verbatim from
Phase 7/8), never calendar time — this is what makes weekend/holiday/
session gaps handle themselves correctly for free, the same way replay
already does. `resolution_as_of` is `candle_complete_at` of the horizon
candle (reused from `app.market_structure.common`), never the resolver's
own wall-clock call time. If fewer future candles exist than the horizon
requires, resolution honestly returns `INSUFFICIENT_FUTURE_DATA` — it never
partially resolves or extrapolates.

Each `ForecastOutcome` stores both a categorical `outcome`
(correct/incorrect/neutral_unresolved/invalidated/insufficient_future_data)
**and** a separate `actual_value` in the same closed vocabulary as
`forecast_value` — the resolver's own determination of what actually
happened. This was added specifically so baselines (below) never have to
try to reconstruct "what really happened" from a binary correct/incorrect
flag alone, which is mathematically underdetermined for any category with
more than two possible values (STRUCTURE has eight).

### Zone re-identification (a correctness fix made during this phase)

`app.support_resistance.ids.zone_id` is, by design, a pure function of
which raw levels cluster into a zone — the exact identity Phase 6 needs for
its own purposes. That means a zone's ID is **not** stable across time: as
soon as one more candle arrives and levels re-cluster, the same physical
support/resistance area routinely gets a new ID. A first draft of
`_resolve_structure` looked up a zone-anchored forecast's referenced zone by
exact ID match against a snapshot rebuilt at `resolution_as_of` — this
failed essentially always, even one bar later, discovered by
`test_structure_forecast_resolves_against_real_future_structure` against
real fixture data. The fix: the resolver fetches the *original* frozen
EvidencePacket (via `evidence_repository.get_packet`) to recover the
original zone's price bounds and kind, then re-identifies "the same
structural level" at resolution time by price-range overlap, scoped to the
original zone's own kind. This is a real, necessary architectural decision,
not a cosmetic one — without it, STRUCTURE forecast resolution would have
been non-functional in practice.

## Baselines (#I) and metrics (#H)

`app.forecasting.baselines.compute_baselines` — always-up, always-down,
no-change/flat (DIRECTION only), matched-unconditional, same-symbol-
historical, and forecast-category baselines — every one computed against
the *same* resolved sample (`ForecastOutcome.actual_value`) a real result is
reported against, never a different population. No forecast performance is
ever presented as skillful without an explicit, displayed baseline
comparison from this exact function.

`app.forecasting.metrics.compute_performance` is the one grouping engine;
every "by X" breakdown (by symbol, timeframe, setup type, catalyst
category, evidence-quality state, origin, horizon) is this same function
called with a different `group_key` — never a parallel, drifting
implementation per breakdown. Every number reported is a plain count,
ratio, or average over an explicit, displayed sample size — directional
accuracy, balanced-style per-category correctness (via `actual_value`),
average forward return, MFE/MAE in ATR terms, coverage rate, and abstention
rate. `overall_performance` on an empty forecast list returns an honest
all-zero/all-`None` breakdown rather than crashing (`IndexError`) — caught
and fixed via the integration test suite's "fresh Forecast Lab, zero
forecasts yet" scenario.

## Historical vs. forward labeling (#J) — structural enforcement of never backfilled

`app.forecasting.service.create_forecast`'s `market_as_of` parameter is
**never exposed by the public API route** (`POST /api/forecasts` in
`app.api.routes.forecasts` has no such field in its request body at all).
Omitting it (the only path the real product ever takes) resolves the
EvidencePacket at real live "now" and tags the resulting forecast
`run_mode=PROSPECTIVE`. Supplying an explicit `market_as_of` — only ever
done by tests, to exercise the resolver against historical fixture data —
tags the forecast `run_mode=BACKTEST_REPLAY` instead, and
`app.forecasting.gate.evaluate_gate` unconditionally filters to
`run_mode == "prospective"` before evaluating anything. A backtest-tagged
row can therefore never contaminate the Forward Validation Gate or be
reported as prospective evidence, structurally rather than by convention —
there is no runtime flag or reviewer discipline standing between a test
fixture and a false prospective claim.

A full product-facing "run a backtest of the forecasting system itself"
feature was deliberately **not** built in this phase. `BACKTEST_REPLAY`
exists solely as an internal testability escape hatch; building a real
backtested-forecast product surface would invite exactly the "we knew the
answer when we wrote the rule" contamination this whole phase exists to
avoid, and is explicitly out of scope until genuine prospective evidence
exists to compare it against.

## Forward Validation Gate (#O) — separate from, never a replacement for, the RANKING GATE

`app.forecasting.gate.evaluate_gate` produces one of `NOT_ENOUGH_DATA` /
`FAIL` / `PROMISING` / `PASS`, from criteria fixed *before* results are
observed (`GateCriteria`: minimum prospective forecast count, minimum
independent resolved episodes, minimum accuracy margin over the best
baseline in percentage points, maximum single-symbol share, maximum
single-time-bucket share, maximum abstention rate). `PASS` requires
clearing every concentration/abstention check **and** beating the best
baseline by the required margin; `PROMISING` is a positive-but-insufficient
margin; anything else is `FAIL`. "Independent episode" is deliberately a
coarse, explicitly-labeled proxy (distinct `(symbol, ISO week)` buckets
among resolved forecasts) — it does not claim Phase 9 episode-grouping
rigor, because `app.research_intelligence.episodes` operates on a different
object (`SetupLedgerEntry`) and forcing a mismatched reuse would have been
worse than an honest, disclosed approximation.

This gate answers a narrower, different question than ADR 0012's RANKING
GATE: "has this forecasting system's prospective track record actually
demonstrated skill over an honest baseline?" — never "should this setup be
ranked or recommended." **The RANKING GATE (ADR 0012) is unaffected and
remains FAIL.** Passing the Forward Validation Gate would never, by itself,
authorize building a ranking or recommendation feature; that remains a
separate decision requiring its own evidence and its own ADR.

## Gate versioning (#P)

`GateCriteria` are persisted (`ForecastRepository.save_gate_version`,
idempotent on `gate_version` the same way a forecast is idempotent on
`forecast_id` — a second save under the same version is a no-op, never a
silent threshold change), and every evaluation is persisted as a new,
timestamped `ForwardValidationGateResultRecord` row
(`save_gate_result`, always insert, never update) — a full evaluation
history accumulates rather than being overwritten. If criteria ever need to
change, that is always a new `gate_version` (`GATE_VERSION = "v1"` today);
there is no code path that edits an existing version's stored criteria.
Goalposts are never moved silently.

## Newly-listed symbols (#N)

The forecasting pipeline contains **no symbol-specific logic anywhere** —
not for any particular newly-public ticker, not for any established one.
Readiness for a stock a few days post-IPO is a property of the existing,
fully generic pipeline honestly reporting what data actually exists, not a
special case that had to be added. This was verified directly
(`tests/unit/forecasting/test_listing_readiness.py`) rather than assumed:
a synthetic symbol with only eight hourly candles (modeling early post-IPO
history) produces an honest `ABSTAINED` VOLATILITY/DIRECTION forecast (ATR/
RVOL/historical-research fields are legitimately unavailable —
`FeatureStatus.INSUFFICIENT_HISTORY`, already Phase 3's own honest
reporting, required no changes here), never a crash and never a fabricated
multi-month sample. A provider that has never heard of a ticker at all
raises `InvalidSymbolError` (already a generic, pre-existing
`MarketDataError` subtype with its own FastAPI exception handler in
`app.main`) — confirmed live in the browser against the real Forecast Lab
UI, which surfaces the clean `"Invalid ticker symbol: '...'"` message rather
than a 500 or a broken page.

## Timestamp semantics (#A, #L)

Every forecast/outcome timestamp (`created_at`, `market_as_of`,
`resolved_at`, `resolution_as_of`) is stored to the second with an explicit
timezone (`datetime`, never a bare string or a date-only field). The
frontend's single formatter, `formatExchangeTimestamp`
(`apps/web/src/lib/format.ts`), renders every one of them as
`YYYY-MM-DD HH:mm:ss EST/EDT` in `America/New_York` via
`Intl.DateTimeFormat(..., { timeZone: "America/New_York", timeZoneName:
"short" })` — verified directly to correctly emit `EST` in January and
`EDT` in July, so DST transitions require no special-casing in application
code. This is the **one** formatter used everywhere a forecast timestamp or
a chart candle timestamp is displayed (the Forecast Lab's tables, and
`CandlestickChart`'s new crosshair-hover readout) — never a current-time
label substituted for a historical instant, and never a second, drifting
formatting implementation.

The chart's x-axis itself is deliberately left uncluttered (lightweight-
charts' own abbreviated tick labels); the full-precision timestamp only
ever appears on crosshair hover, via a `subscribeCrosshairMove` handler
added to `CandlestickChart` — confirmed live in the browser
(`2026-09-03 11:30:00 EDT`) via the actual rendered tooltip element's own
text content, not merely by reading the code.

## No ranking / no recommendation policy

Nothing in this phase, at any layer, ever outputs BUY, SELL, STRONG BUY, a
price target, a portfolio weight, or a numeric confidence/probability. No
new ranking or scoring engine was created. The Forecast Lab UI's own header
states this explicitly. This is not merely a UI-copy choice — it is
mechanically enforced the same way Phase 11's grounding validator enforces
it (`_BANNED_PATTERNS` screening, closed-enum forecast values, no free-text
prediction field anywhere in `ForwardForecast`). RANKING GATE (ADR 0012)
remains **FAIL**; no brokerage/execution connection exists or was added.

## API surface (#Q)

`POST /api/forecasts` (never accepts `market_as_of` — see above), `GET
/api/forecasts` (list, filterable by symbol/timeframe/status), `GET
/api/forecasts/{id}`, `POST /api/forecasts/{id}/resolve` (idempotent — a
second resolve request on an already-resolved forecast returns the existing
outcome rather than re-resolving), `GET /api/forecasts/performance`, `GET
/api/forecasts/gate`. Every route is thin orchestration only — no
detection/statistics logic lives in a route file, the same convention every
route module since Phase 7 has followed.

## Limitations

- The Forecast Lab UI's "RESOLVE" action is user-triggered, not an
  automatic background job — a real prospective forecast can only honestly
  resolve once its horizon has genuinely elapsed in wall-clock time, so
  there was no automation to build that wouldn't just be polling; clicking
  RESOLVE before the horizon closes correctly and honestly reports
  `INSUFFICIENT_FUTURE_DATA` rather than blocking or erroring.
- `_independent_episode_estimate`'s `(symbol, ISO week)` bucketing is an
  explicitly coarse proxy, not Phase 9-level episode-independence rigor.
- No probability/confidence output exists yet, by design (#E) — this
  remains true until real prospective calibration evidence exists, which is
  the entire reason this phase was built.
- `MarketDataProvider` still has no true ranged historical fetch (ADR
  0015's limitation, unchanged) — newly-listed-symbol reach is bounded by
  whatever the provider's own retention actually returns, reported honestly
  via the same `FeatureStatus`/`SetupDetectionStatus` insufficient-history
  states Phase 3/6 already had.

RANKING GATE remains **FAIL** (ADR 0012). Phase 13 is not started by this
work.
