# ADR 0013: News & Catalyst Context Engine (Phase 10)

## Motivation

Phases 1-9 built a deterministic price/structure/setup pipeline and a
statistical evidence layer, and Phase 9 (ADR 0012) concluded with an
explicit **RANKING GATE: FAIL** -- the evidence does not yet justify a
calibrated, scored ranking engine. Phase 10 does not revisit that gate. It
adds a different, complementary thing: context. A user looking at a
detected setup, or at the market in general, wants to know *what happened*
around a symbol -- an earnings release, a downgrade, a macro print -- and
whether the setup formed before or after it, and how price/volume/structure
actually reacted. That is research evidence and context, never a trading
signal. This ADR states the boundary explicitly and holds it throughout:

**News/catalyst data provides context and research evidence. It is NOT a
deterministic assumption that "good news = buy" or "bad news = sell."**
Nowhere in this phase does a catalyst category, a reaction number, or a
`SetupCatalystContext` label resolve to a buy/sell/hold recommendation, a
0-100 score, or an AI confidence percentage. The dashboard-facing vocabulary
is deliberately small and descriptive (`SetupCatalystContextLabel`): catalyst-
supported, catalyst-conflicted, catalyst-reaction-faded, catalyst-reaction-
persisted, catalyst-timing-ambiguous, no-recent-catalyst -- nothing else.

## Architecture

A new top-level package, `app/news/`, follows the same shape every prior
engine in this codebase uses: a `schemas.py` of frozen pydantic models, a
`config.py` of centralized thresholds, pure deterministic functions, and a
persistence layer with an ABC + a single `SqlAlchemy*` implementation.
Consistent with the whole codebase's layering discipline, `app/news/`
**consumes** already-computed Phase 4/5 structure/levels snapshots and
Phase 7 outcome-measurement machinery; it never recomputes them:

```
NewsProvider
  -> normalization.py (raw payload -> NormalizedNewsArticle, classified)
  -> events.py (deterministic grouping -> CatalystEvent)
  -> reaction.py (reuses app.research.outcomes' horizon/excursion math)
  -> setup_linking.py (SetupCandidate + events + reactions -> SetupCatalystContext)
  -> repository.py (persistence, idempotent, as_of-safe)
  -> api/routes/news.py, api/routes/research_catalysts.py
```

Two existing packages gained small, additive extensions rather than a
parallel implementation:

- `app.research_intelligence.cohorts`: three new `CohortDimension` members
  (`CATALYST_CATEGORY`, `TIME_SINCE_CATALYST_BUCKET`, `CATALYST_RVOL_ELEVATED`)
  and an optional `catalyst_context_by_setup_id` parameter threaded through
  `cohort_dimension_value`/`cohort_key`/`group_by_cohort` -- the exact same
  pattern `partition_by_setup_id` already established. Every existing call
  site that doesn't pass the new parameter is unaffected.
- `app.research_intelligence.analogs`: `AnalogFeatures` gained two optional
  fields (`catalyst_category`, `catalyst_recency_bucket`), `extract_features`
  gained an optional `catalyst_context` parameter (default `None`).
  Un-opted-in callers get byte-identical output to before this phase.

## Provider abstraction (#A)

`app.news.provider.NewsProvider` is an ABC with two methods,
`fetch_symbol_news`/`fetch_market_news`, each taking an explicit `as_of` --
mirroring `app.market_data.provider.MarketDataProvider` exactly. Two
implementations exist:

1. **`FixtureNewsProvider`** (`fixture_provider.py`) -- deterministic,
   constructed from a fixed list of raw article dicts, normalizes once at
   construction time. Every test in `tests/unit/news/` uses this.
2. **`YFinanceNewsProvider`** (`yfinance_provider.py`) -- wraps
   `yfinance.Ticker.news`. **DEVELOPMENT/RESEARCH ONLY**, stated in the
   module's own docstring, not just here. Verified live against real AAPL
   data (2026-08-31): the response shape is `[{"id": ..., "content": {...}}]`
   with `content.title`, `content.pubDate` (ISO-8601 UTC), `content.provider
   .displayName`, `content.canonicalUrl.url`, `content.contentType`. Every
   field is read defensively (`.get`, not attribute access); a malformed
   item is skipped with a warning, never crashes the batch. No
   yfinance-specific dict shape leaks past this one file.

Provider selection is one config value (`NEWS_PROVIDER`, default
`"yfinance"`), read in exactly one place (`app/api/deps.py::get_news_provider`),
same convention as `MARKET_DATA_PROVIDER`.

## Licensing limitations (#O)

Stated plainly, not buried: `yfinance.Ticker.news` is an **unofficial**
interface into Yahoo Finance's own news aggregation, not a licensed,
redistributable commercial feed. It is suitable for local development and
research only. It is also **not a queryable historical archive** -- there is
no `start=`/`end=` parameter Yahoo honors; the endpoint returns whatever
Yahoo currently has cached as "recent" for a ticker. This provider can
never backfill news from an arbitrary past date range, which is exactly why
every test and every piece of historical-analysis logic in this phase runs
against `FixtureNewsProvider`, not against yfinance. A commercial deployment
needs a properly licensed news/data provider (a licensed newswire or a
market-data vendor's news product). Swapping one in means writing one more
class satisfying `NewsProvider` -- nothing downstream of the provider
boundary changes, by construction (same reasoning ADR 0006 already
documents for `MarketDataProvider`). The architecture was deliberately kept
free of any yfinance-specific field name outside `yfinance_provider.py`.

## Normalized article model (#B)

`NormalizedNewsArticle` (frozen pydantic model) carries: `article_id`
(stable, sha256-derived from provider+source+headline+published_at+url --
see below), `provider`, `source`, `headline`, `published_at`, `received_at`,
`url`, `symbols` (normalized via the same `normalize_ticker` the rest of the
app uses, invalid symbols silently dropped rather than fabricated),
`raw_category`, `classification` (the full `CatalystClassification`, not
just a label), `provenance`, `ingested_at`. **Full article bodies are never
stored or fetched** -- only headline + structured metadata + a link to the
original source. Missing fields stay `None`; nothing is ever defaulted to a
fabricated value.

## Catalyst taxonomy (#C)

25 categories (`CatalystCategory`, including `unknown` as a real, permanent
value -- never a placeholder expected to disappear). Classification
(`app.news.classification.classify_article`) is a fixed-priority,
deterministic rule chain: (1) a small provider-category direct-map, (2)
ordered strong-keyword-phrase rules (most specific first, e.g. earnings
preannouncement before plain earnings), (3) weak single-word fallbacks, (4)
`unknown` if nothing matches. Every classification records a discrete
`ClassificationBasis` tier (`provider_category_direct_map` /
`strong_keyword_match` / `weak_keyword_fallback` / `unknown_no_match`) --
**deliberately not a fabricated confidence float**; a fitted or invented
0-1 confidence number would misrepresent a rule-based classifier, so this
phase reports which tier matched instead. `ClassificationMethod` is always
`deterministic_rule` today; `ai_assisted` exists in the enum only so a
future AI-assisted layer has somewhere to record itself as a **separate**,
additional classification, never a mutation of the deterministic one
already on the immutable article.

## Event grouping/deduplication (#D)

`app.news.events.group_into_events` is a pure function: process articles
chronologically; a candidate joins the first open group whose anchor (the
group's own earliest article) shares at least one symbol, the same
normalized category, and whose `published_at` falls within
`event_grouping_window_hours` (12h default) of that anchor -- **anchored to
the group's first article, not chained article-to-article**, so a slow
drip of same-topic follow-ups over days cannot merge one hour at a time (the
product spec explicitly rejected pure time-proximity merging; a real test,
`test_article_outside_anchored_window_starts_a_new_event`, proves an article
20h after the anchor starts a new event even though it is within 12h of the
group's second member). `event_id` is a sha256 hash of the sorted member
`article_id`s -- deterministic and reproducible for a fixed input set. Every
source article is preserved (`contributing_article_ids`); grouping never
discards or merges article content away.

## Anti-lookahead semantics (#E)

The non-negotiable section, held by construction rather than by convention
alone: `group_into_events` is stateless and reads no persisted "current"
event row. `app.news.repository.SqlAlchemyNewsRepository
.events_for_symbol_as_of(symbol, start, end, as_of)` **always** re-derives
events fresh from `get_articles_for_symbol` (itself filtered defensively to
`published_at <= as_of`, independent of caller correctness -- the same
"never trust the caller alone" convention `app.market_structure.common
.truncate_to_as_of` already established) and then calls `group_into_events`
on that as_of-bounded set, every single call. Because grouping is
deterministic given a fixed input set, a historical as_of query is
mathematically incapable of changing when a later, future-dated article is
subsequently ingested -- proven directly by
`test_repository_as_of_query_is_unaffected_by_a_later_ingested_article` in
`tests/unit/news/test_as_of.py`. The persisted `catalyst_events` table
(`list_recent_events`) is an explicit, separately-documented exception: a
materialized cache of the *current* grouping, used only for the "what's
moving right now" dashboard view, and is never consulted by any as_of-aware
query path. `SetupCatalystContext` construction (`setup_linking.py`)
performs no fetching itself; it only ever sees whatever `events`/
`reaction_by_event_id` its caller already as_of-filtered, so lookahead is
structurally impossible to introduce at that layer either.

## Reaction measurement (#F)

`app.news.reaction.measure_market_reaction` reuses
`app.research.outcomes.compute_horizon_outcomes`/`compute_excursion`/
`forward_candles` verbatim -- horizons are bar-based (1/3/5/10/20 bars),
the same convention every deterministic engine in this codebase already
uses, not literal clock offsets, since a catalyst's exact timestamp rarely
aligns to a bar boundary. The "base candle" is the last candle at or before
the event's `primary_timestamp`; reaction is measured in a **neutral,
always-bullish convention** (`directional_return_percent == raw_return_percent`
always) -- reinterpreting a reaction relative to a specific setup's own
direction is `setup_linking.py`'s job, done strictly after this
direction-neutral measurement. RVOL reuses `app.features.volume
.average_volume` verbatim. Session classification
(`ReactionSession`: pre-market/regular/after-hours/weekend-non-trading)
adds a genuine weekend check on top of `app.market_data.sessions`' intraday
classifier, since a catalyst (unlike a candle) can be published at any
wall-clock moment including a non-trading day -- this is what correctly
prevents an after-hours or weekend catalyst from being scored against the
wrong day's first reaction candle. Structure fields (nearest S/R,
BOS/CHOCH-after) are attached by a separate, explicitly read-only decoration
pass (`attach_structure_context`) from already-computed Phase 4/5 snapshots
-- this module never recomputes structure itself.

## Setup <-> catalyst linkage (#G)

`app.news.setup_linking.build_setup_catalyst_context` implements a fully
documented, explicit-priority-order decision rule (mirroring
`evidence_maturity.py`'s "priority order matters, and here is why"
convention) that never produces anything outside the six-label vocabulary.
In order: no catalyst in the lookback/lookahead window ->
`no_recent_catalyst_found`; nearest catalyst within
`timing_ambiguous_window_minutes` (30 min default) of detection ->
`catalyst_timing_ambiguous`; no usable reaction evidence yet ->
`catalyst_timing_ambiguous`; otherwise the catalyst's first-available-horizon
reaction, **realigned to the setup's own direction** -- below a negative
threshold -> `catalyst_conflicted_context`; above a positive threshold ->
`catalyst_supported_context`, further refined by a persistence ratio
(latest-available-horizon / first-available-horizon) into
`catalyst_reaction_faded` / `catalyst_reaction_persisted` / staying
supported when persistence is inconclusive; a genuinely small/inconclusive
initial reaction -> `catalyst_timing_ambiguous`. Every branch's
`label_basis` is a human-readable string stating exactly which numbers
drove the decision -- never an unexplained label. 13 unit tests
(`tests/unit/news/test_setup_linking.py`) exercise all six labels plus the
bullish/bearish realignment.

## Historical catalyst research (#H)

Rather than building a second statistics stack, `app/api/routes
/research_catalysts.py`'s `POST /api/research/catalysts/query` computes each
pooled ledger entry's `SetupCatalystContext` (batched per-symbol via the
shared `build_setup_catalyst_contexts_batch` helper -- one news
fetch/grouping/reaction pass per distinct symbol, never per entry),
**pre-filters** the entry pool by the requested catalyst criteria
(`require_catalyst`, `catalyst_category`, `catalyst_max_hours_since`,
`catalyst_rvol_elevated`), then hands the filtered pool to
`compute_research_query_response` -- the exact same evidence-card/decay/
excursion/stability/concentration/overlap/contradictions/independence
pipeline `/api/research/query` already runs, extracted into a shared
function so not one line of Phase 8/9 statistics is duplicated. A query for
"earnings + breakout_retest" is simply `setup_type=breakout_retest,
catalyst_category=earnings`; "catalyst with elevated RVOL vs without" is two
calls differing only in `catalyst_rvol_elevated`. The response discloses
`catalyst_filtered_sample_count` alongside `unfiltered_sample_count` and the
exact filters applied, so a small resulting sample is never hidden. This is
a deliberate scoping choice, not full parity with Phase 8/9's
purpose-built cohort-comparison UI: it reuses filtering rather than
building a second parallel walk-forward/purged-sampling stack specifically
for catalyst dimensions, which would have meant re-deriving Phase 8/9's
entire apparatus a second time for uncertain added value this phase's
timeline did not justify.

## Historical analog engine extension (#I)

`extract_features(candidate, detection_close, catalyst_context=None)` --
the default reproduces every existing analog test byte-for-byte.
`POST /api/research/analogs` gained `include_catalyst_context: bool = false`;
when true, `catalyst_category`/`catalyst_recency_bucket` are populated from
each candidate's own `SetupCatalystContext` (computed strictly from
information available as of that candidate's own detection instant --
`build_setup_catalyst_contexts_batch` never looks past it) and contribute to
`distance_between` like any other categorical dimension; when both sides
lack context they report as `missing_dimensions`, contributing nothing.
`tests/unit/research_intelligence/test_analogs_catalyst.py` directly proves
two otherwise-identical candidates can rank differently once catalyst
context is included, and that `AnalogFeatures` has no field capable of
holding outcome/return data -- future outcome data is structurally
incapable of influencing ranking here, not merely conventionally avoided.

## UI decisions (#K)

Three integration points, all descriptive, none containing BUY/SELL/STRONG
BUY/a confidence percentage:

1. **What's Moving the Market** (`WhatsMovingPanel.tsx`) -- aggregates
   catalyst events across the user's own watchlist (yfinance has no true
   market-wide endpoint; documented, not silently faked with a made-up
   "market news" call). Click-to-expand per card fetches source articles and
   a one-symbol reaction snapshot, never an always-on network call for every
   card on render.
2. **Symbol Catalyst Timeline** (`SymbolCatalystTimeline.tsx`) -- the
   catalyst -> price reaction -> volume reaction -> structure change ->
   setup formation sequence, per event, click-to-expand.
3. **Setup Intelligence's Catalyst Context** (`CatalystContextCard.tsx`) --
   embedded in each expanded setup card, click-to-load (same discipline
   `AnalogSearchButton` already established), showing the nearest
   catalyst's category/timing/source count/initial reaction/RVOL/structure
   plus the deterministic label, with `VIEW CATALYST` (source articles) and
   `VIEW HISTORICAL CATALYST ANALOGS` (the extended analog engine with
   `include_catalyst_context: true`, reusing `AnalogSearchButton` itself via
   a new optional prop rather than a parallel component).

Article display everywhere is headline + source + timestamp + external link
only -- no article body is ever embedded or reproduced, and no visual design
imitates any named news outlet.

## Persistence (#L)

Four new tables (`0005_news_catalyst_tables` migration, same dialect-agnostic
`op.create_table` convention as 0002-0004): `news_articles` (unique on the
content-derived `article_id`, making re-ingestion idempotent by
construction -- proven by `test_no_duplicate_article_created_on_re_ingestion
_across_reopen`), `catalyst_events` (unique on `event_id`), `catalyst_event
_articles` (an explicit membership join table alongside, never instead of,
`catalyst_events.contributing_article_ids`), `catalyst_reactions` (unique on
`event_id, symbol, timeframe` -- reaction is symbol-specific even for a
market-wide event). One real, general SQLite limitation was found and fixed
during this phase: `DateTime(timezone=True)` columns round-trip as naive
datetimes on SQLite (unlike Postgres) even though every value is written as
UTC -- `app.news.repository._ensure_utc` reattaches UTC tzinfo defensively
on every raw-column read, the same "never trust the read path alone"
convention the rest of this module already follows. Every test that opens a
file-backed SQLite database inside a `tempfile.TemporaryDirectory` closes
and disposes its session/engine in `try/finally` before the directory
context exits -- the exact Windows file-lock fix applied to Phase 7's
persistence tests earlier this project, applied proactively here rather
than discovered by a second failure.

## Known limitations

- The yfinance dev provider cannot backfill historical news (see
  Licensing limitations above) -- all historical/anti-lookahead testing
  necessarily runs against `FixtureNewsProvider`.
- Classification keyword coverage is a real, finite, hand-written list (see
  `app/news/classification.py`); a headline phrased unusually classifies as
  `unknown` rather than being force-fit, which is correct behavior, but
  means recall is imperfect -- expanding the keyword rules over time is
  expected maintenance, not a design flaw.
- Event grouping still groups two `unknown`-category articles about the
  same symbol within the time window together, since no stronger
  distinguishing signal exists yet -- a documented, deliberate trade-off,
  not a silent one.
- `/api/research/catalysts/query` pre-filters rather than running a second
  full independence-adjustment stack (walk-forward/purged-sampling) *scoped
  to catalyst cohorts specifically* -- it inherits whatever independence
  adjustment the underlying pooled entries already carry, but does not
  re-run purged-sampling *within* the catalyst-filtered subset as its own
  independent step. A future phase could add that if catalyst-scoped
  research proves valuable enough to justify it.
- `WhatsMovingPanel` is watchlist-scoped, not truly market-wide, for the
  same yfinance-limitation reason.
- `POST /api/research/catalysts/query` has no dedicated Research Lab UI
  section in this phase -- the backend endpoint is complete and tested, but
  the frontend integration built this phase is the analog engine's
  `include_catalyst_context` toggle (reachable from Setup Intelligence) and
  the dashboard/timeline/setup-context surfaces; a Research Lab panel for
  building catalyst-cohort queries interactively is a natural next step,
  not yet built.

## Commercial data-provider requirement

To ship a commercial product, `NEWS_PROVIDER` must point at a properly
licensed provider implementing `app.news.provider.NewsProvider` --
nothing else in this phase's architecture assumes yfinance or any other
specific vendor's field names. This is the same swap-one-class boundary
`MarketDataProvider` already proved out for market data in ADR 0006.
