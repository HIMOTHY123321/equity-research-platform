# ADR 0015: Point-in-Time Evidence Integrity (Phase 11.1)

## Motivation

Phase 11's EvidencePacket scoped "live" market-derived sections (features/
structure/S&R/setup) and "historical" catalyst/research sections
differently: the latter were genuinely `as_of`-bounded; the former reused
the live routes' fixed-size candle fetch regardless of how historical
`as_of` was. That was an acceptable, explicitly-documented scoping decision
to ship Phase 11 safely, but it left one real gap: **a historical
EvidencePacket was not yet guaranteed to represent exactly what the
platform knew at that instant.** This phase closes it.

## Audit findings (#A)

Before writing any code, every subsystem's actual truncation/confirmation
logic was read (not assumed safe from a function signature). Nearly all of
it was already genuinely point-in-time safe by construction:

| Subsystem | Finding |
|---|---|
| Features, previous-day/week, structure, pivots, BOS/CHOCH, S/R zones, setup detection (qualified/rejected), catalyst/news | **Fully historical-safe already.** Every engine defensively re-truncates to `as_of` itself (`truncate_to_as_of`, `completed_only`), independent of caller correctness. Pivots use `confirmed_at` gating (`right_bars` completion); BOS/CHOCH run a chronological simulation gated on `swing.confirmed_at <= known_at`; S/R zones only see candles from `zone.known_at` onward. |
| Historical analog feature extraction | **Fully isolated already.** `extract_features` reads only `candidate.context`/`fingerprint` (frozen at detection) plus a detection-instant close lookup; `attach_outcomes` is a strictly separate, later pass. |
| Research ledger/replay | **Already the canonical pipeline.** `app.research.replay.run_replay` calls the *exact same* `compute_feature_snapshot`/`compute_market_structure_snapshot`/`compute_support_resistance_snapshot`/`compute_setup_detection_snapshot` functions, windowed per bar -- there was never a second implementation to reconcile. |
| **EvidencePacket's market-data sourcing** | **The one real gap.** `MarketDataProvider.get_candles(limit=N)` only ever returns "the latest N candles as of real now" -- there is no ranged historical fetch anywhere in this codebase (`fetch_candles_cached`'s `requested_start`/`requested_end` are a cache key, never an actual fetch bound). Phase 11's packet builder fetched a fixed, live-sized `N` regardless of `as_of`, so a sufficiently historical `as_of` could leave too few -- or zero -- candles after truncation, even though the provider genuinely still had that history further back. |
| Grounding validator | Partially safe -- a text-scanning heuristic only, no typed fact-to-evidence-object check. Addressed below (#I). |

## Canonical point-in-time pipeline (#B)

`app/ai_analysis/market_snapshot.py::build_market_snapshot(symbol,
timeframe, provider, as_of)` is now the one place market data is sourced
for *any* point-in-time snapshot -- no engine logic is duplicated; it
composes the identical Phase 3-6 functions replay and the live routes
already used. `app.api.routes.market.get_setups` (proven byte-identical
pre/post-refactor by the full `test_market_routes.py` suite) and
`app.ai_analysis.evidence_packet.build_evidence_packet` both call it now;
"live" is simply the case `as_of=datetime.now()`, never a structurally
different code path.

### Candle-depth fix

`_required_candle_count` sizes the provider fetch from `as_of`'s age
instead of a fixed constant, so the fetch actually reaches back far enough
to cover `as_of`. If the provider's own retention genuinely doesn't reach
that far, the existing `FeatureStatus.INSUFFICIENT_HISTORY` /
`SetupDetectionStatus.UNAVAILABLE` data_quality reporting -- already built
into those engines for exactly this situation -- correctly says so. No new
"unavailable" concept was invented.

### Window-boundary fix (replay parity, #F)

The over-fetched candles are trimmed to the same trailing window size
(`CANDLE_LIMIT_BY_TIMEFRAME`) every other pipeline uses, using **strict**
`timestamp < as_of` rather than the shared (`<=`) `truncate_to_as_of`.
This was discovered empirically: `tests/unit/ai_analysis/test_replay_
parity.py` initially failed with a differing ATR value for a setup replay
detected first, versus the same instant queried through the canonical
pipeline. Root cause -- for back-to-back intraday bars,
`candle_complete_at(candle_N)` is numerically identical to
`candle_N+1.timestamp`; an inclusive `<=` boundary therefore handed the
feature engine one additional (just-opened, still-forming) candle that
`run_replay`'s own `candles_sorted[idx+1-window_limit:idx+1]` window never
included, producing a different Wilder-ATR seed for the textually-identical
`as_of`. Every engine still independently truncates defensively with its
own `<=`; this is purely a window-*selection* choice made once, at the
candle-sourcing layer, so replay and the canonical pipeline agree.

## Candle completeness / confirmation rules (#C)

All pre-existing, reconfirmed rather than re-implemented:
- A candle after `as_of` never exists in a truncated series (`truncate_to_as_of`, `<=`, used inside every engine).
- A still-forming trailing candle is used by *continuous* features (ATR, MAs) exactly as documented, and excluded from *discrete* pattern/structure detection via `completed_only`/`is_candle_complete`.
- A pivot's `confirmed_at` is the earliest instant its `right_bars` requirement was actually satisfied by completed data -- never backdated.
- BOS/CHOCH only ever reference a swing once `swing.confirmed_at <= known_at` for the evaluating candle.
- An S/R zone's own `known_at` bounds which candles can even be considered for its interactions/breaks.
- Previous-day/week levels are gated on `exchange_trading_date(candle) < today` plus their own `known_at`.
- A future retest, future catalyst, or future article can never retroactively create or alter an earlier setup/event -- proven empirically below, not just asserted.

## Append-future invariant (#E)

`tests/unit/ai_analysis/test_append_future_invariants.py` builds a
synthetic, fully-controlled zigzag candle series and proves, for pivots,
BOS/CHOCH, S/R zones, qualified/rejected setup candidates, and
invalidation criteria: identical output whether evaluated against the past
data alone, an ordinary continuation, or an *adversarial* future (a price
spike orders of magnitude beyond anything seen) appended after `as_of` --
with a companion test proving the adversarial fixture would have changed
output if it had leaked, so the invariance proof isn't vacuous.
`test_evidence_packet_determinism.py` proves the same for whole-packet
composition (candles, news, research runs).
`test_claims_historical_safety.py` and `test_analog_detection_time_
isolation.py` extend this to EvidenceClaims and analog ranking
respectively.

## EvidencePacket cutoff semantics (#D)

Every packet now carries, alongside `as_of`:
- `mode`: `live` or `historical_snapshot` -- reflects **caller intent**
  (did the caller pass an explicit `as_of`?), never inferred from clock
  proximity, so a recently-past `as_of` is still honestly labeled
  historical.
- `market_data_cutoff` / `news_cutoff` / `research_snapshot_cutoff` --
  the actual latest instant each category's evidence reflects. Never
  assumed equal to `as_of`; when market data cannot reach back that far,
  `data_quality.missing_evidence` records it explicitly rather than
  silently mixing current structure with historical catalyst/research.
- `pipeline_version` (the market-snapshot composition version) alongside
  the pre-existing `schema_version` (the packet's own JSON shape).

## Replay <-> live parity (#F)

`test_replay_parity.py` runs `run_replay` over the real SPY fixture and, for
a sample of first-detected setups, asserts the canonical pipeline called
directly with `as_of=entry.first_seen_at` reproduces the *exact* frozen
`SetupCandidate` (full field equality) replay recorded -- proving the two
pipelines are the same pipeline, not just similar.

## AI brief historical binding (#H)

A `ResearchBrief` always carries `evidence_packet_id`; fetching a persisted
brief (`GET /api/analysis/{symbol}/brief/{id}`) is a pure repository read
that takes no market-data provider at all -- structurally incapable of
recomputing against today's state. The mock provider remains
byte-reproducible given the same packet (`test_mock_brief_is_deterministic`,
Phase 11); a real provider's output is never claimed to be.

## Grounding validator hardening (#I)

Layered on top of (never replacing) the existing evidence-ref/numeric-
grounding/banned-language checks, three **typed** checks now validate
specific statement shapes against the *specific* field they claim to
describe, not just "this number appears somewhere in the packet":
- A price described as a resistance/support level must match an actual
  zone's price (tolerance: max(0.01, 0.5%)).
- An episode/sample count must equal the packet's own independence-adjusted
  counts exactly.
- A catalyst timing claim ("Nh before/after setup") must be derivable from
  the packet's actual catalyst timestamps (tolerance: 0.5h).

This closes a real precision gap: previously, a claim like "$999 resistance"
could pass the generic numeric check if 999 coincidentally matched some
*unrelated* grounded number (e.g. a sample count) elsewhere in the packet.
Deliberately narrow: subjective prose is never typed-checked, only
statements with an unambiguous quantitative shape.

## Prompt-injection boundary (#J)

Extended the banned-language set with defense-in-depth patterns for
prompt-injection-style phrasing appearing in a brief's own text (fabricated
"system message" framing, a fabricated RANKING GATE override claim, a
fabricated win-rate claim) alongside the pre-existing BUY/SELL/probability
patterns. External untrusted text (headlines, sources) was already
structurally safe (embedded as inert JSON data, never string-concatenated
into instructions) and already tested; this pass adds the case where a
compromised/misbehaving provider echoes or acts on such phrasing in its own
output.

## Audit trail UI (#K) / LIVE vs HISTORICAL mode (#L)

"VIEW EVIDENCE PACKET" is now a structured audit surface
(`EvidenceAuditTrail.tsx`) with named sections -- packet id/as-of/pipeline
version, market/news/research cutoffs, setup/structure/level/research/
catalyst/analog evidence, and the brief's evidence-ref citations -- with raw
JSON demoted to an explicit secondary "developer view" toggle. A
LIVE/HISTORICAL SNAPSHOT badge reflects `EvidencePacket.mode` directly.
**Scope note**: the badge and backend `mode` field are wired end-to-end;
a dedicated UI control for *choosing* a historical `as_of` to browse was
not added in this pass (the API already accepts one) -- left for a future
phase if a real product need for browsing arbitrary historical instants
emerges.

## Caching (#N)

No new caching was introduced. The over-fetch in `build_market_snapshot`
is not cached beyond what `CachedMarketDataProvider`'s existing TTL cache
already does transparently underneath every provider call. If caching is
ever added here, the cache key must include `as_of`, `symbol`/`timeframe`,
and pipeline/config version -- a cache hit must never be able to return a
result derived from data that postdates the request's own `as_of`.

## Limitations

- `MarketDataProvider` still has no true ranged historical fetch; reach is
  bounded by how much the provider will return for a given `limit`
  (capped at 50,000) and by the provider's own actual retention (e.g.
  yfinance intraday's real-world history window). This is now reported
  honestly via existing insufficient/unavailable data_quality states
  rather than silently producing a thin snapshot.
- The strict window-boundary fix (#F) is a window-*selection* convention
  for parity, not a new anti-lookahead mechanism -- every engine's own
  defensive truncation is unchanged.
- No historical-`as_of` picker UI; the capability is API-level only in this
  pass.

RANKING GATE remains **FAIL** (ADR 0012). Nothing in this phase computes a
score, rank, or recommendation.
