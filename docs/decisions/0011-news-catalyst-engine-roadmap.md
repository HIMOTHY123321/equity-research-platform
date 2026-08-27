# ADR 0011: News/Catalyst Engine — future roadmap (not built this phase)

## Status

Roadmap only. No code in this ADR is implemented as of Phase 8. Documented
now, per explicit direction, so the architecture Phase 8 lands on doesn't
foreclose this later — but building it is deliberately out of scope until
its own dedicated phase.

## What this is not

- Not a trading signal. "Good headline → buy" / "bad headline → sell" is
  explicitly rejected — see the reaction-measurement pipeline below, which
  treats news as *context* attached to price/volume/structure/setup
  research, never as an input a detector acts on directly.
- Not scraped or reproduced article content. Only metadata (headline,
  source, published_at, URL, affected symbols, category, a stable event
  ID) from providers this product has the rights to use is stored;
  full article bodies are never stored or displayed, and the UI links out
  to the source rather than reproducing it. No New York Times UI, styling,
  or copy is imitated.
- Not an LLM feature. Classification into the category list below is a
  provider-supplied or deterministic mapping, not a model call — same
  "no AI yet" boundary the rest of Phase 8 holds. An eventual AI layer
  (post-evidence-layer, per ADR 0010's non-goals) would *interpret*
  already-verified news/reaction/research data; it would not generate or
  infer news content itself.

## Proposed pipeline

```
NewsProvider
  -> NormalizedNewsEvent
  -> Ticker Mapping
  -> Catalyst Classification
  -> Market Reaction Measurement
  -> Research Context
```

- **NewsProvider**: an abstraction over one or more licensed/supported news
  APIs, mirroring `MarketDataProvider`'s existing pattern (`app/market_data/
  provider.py`) — an ABC with a concrete implementation per vendor, so the
  vendor can change without touching downstream code.
- **NormalizedNewsEvent**: headline, source, `published_at`, URL, a stable
  `event_id`, and the raw affected-symbol list the provider reports —
  the only article content ever persisted.
- **Ticker Mapping**: resolves provider-reported symbols against this
  app's own symbol table (`app.database.models` `Symbol`), the same
  normalization `app.schemas.symbols.normalize_ticker` already does for
  market data.
- **Catalyst Classification**: earnings / guidance / analyst action /
  product launch / regulatory / lawsuit / M&A / macro / Fed-rates /
  geopolitical / supply chain / company filing / management change —
  provider-supplied category where available, otherwise a deterministic
  keyword/metadata rule, never an LLM call.
- **Market Reaction Measurement**: reuses this phase's own machinery
  rather than inventing new statistics — price/volume reaction at fixed
  horizons after `published_at` is structurally the same computation as
  `app.research.outcomes.compute_horizon_outcomes`/`compute_excursion`
  (a "detection instant" plus forward candles), so a catalyst event can be
  evaluated with the exact same horizon/MFE/MAE machinery Phase 8 already
  built and tested, not a parallel implementation.
- **Research Context**: the eventual point of contact with
  `app.research_intelligence` — a catalyst becomes one more cohort
  dimension (e.g., "breakout_retest with a same-day earnings catalyst" vs.
  "without") that `cohorts.py`/`comparison.py::compare_groups` can already
  express without modification, once catalyst-tagged entries exist to
  group on.

## Proposed persistence

New tables only, additive to the existing schema, no changes to Phase 1-8
tables: `news_events` (event_id, headline, source, published_at, url,
category, raw_symbols JSON, created_at) and `news_event_symbols`
(news_event_id, symbol, many-to-many) — same `_portable_uuid_pk()` /
migration convention as every table added since ADR 0008.

## Future dashboard surface (not built)

Per-symbol "MARKET NEWS" section: headline, source, relative time,
category, `published_at`, price-at-publication, 15m/1h reaction,
volume-after-publication, and a "Read source" link out — never an inline
reproduction of the article. A cross-symbol "What's Moving the Market"
view groups today's higher-relevance catalysts by symbol. Both are
deliberately not implemented now; building them with fabricated example
data was explicitly rejected in favor of documenting the shape and
building it for real once this becomes its own phase.

## Why this waits

Phase 8's evidence layer (baselines, qualification lift, decay, excursion,
temporal/cross-symbol stability, analogs, contradictions) is the
foundation a catalyst dimension would sit on top of — cohort-splitting by
"has catalyst" only produces a meaningful comparison once the underlying
statistical machinery it's compared against already exists and is trusted.
Building news ingestion before that foundation was solid would have meant
building a comparison feature with nothing reliable yet to compare against.
