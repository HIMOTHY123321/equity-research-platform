# AI Market Desk

An AI-assisted market research, backtesting, and prediction-tracking terminal.
It is **not** an autonomous trading bot: the current version scans a
watchlist on a schedule, computes technical/price-action features and
detects setups deterministically in code, asks an LLM to interpret (never
compute) that already-verified data, ranks setups, tracks every prediction
against real subsequent price data, and reports whether the system's ideas
actually worked. Execution, when it exists, is paper trading only.

## Why this exists

The most important loop in this codebase is:

```
analyze → predict → save prediction → wait for real market data
        → grade the prediction → measure performance → improve the rules
```

Every setup the app surfaces is measurable. See [`docs/decisions/`](docs/decisions)
for the reasoning behind specific design choices as they accumulate.

## Architecture

```
market-data → feature-engine → market-structure-engine → support/resistance-engine
  → setup-detectors → setup-scoring-engine → risk/reward-engine
  → ai-analysis-engine → database → dashboard / reports / backtesting
```

Everything through `risk_reward` is deterministic Python (pandas/numpy),
unit-tested, and produces validated, typed output. `ai_analysis` is the only
module allowed to call an LLM, and only after the deterministic layer has
already computed every number — the AI interprets, it never invents prices,
indicators, or levels. A validator rejects any AI response containing a
numeric value that doesn't trace back to the deterministic computation.

## Repository layout

```
apps/
  web/            Next.js + TypeScript + Tailwind + TradingView Lightweight Charts
  api/
    app/
      market_data/          fetch + normalize OHLCV candles (Alpaca)
      features/             deterministic technical calculations
      market_structure/     swing/trend/break-of-structure detection
      support_resistance/   deterministic level detection
      setup_detection/      one module per price-action pattern
      scoring/              deterministic 0-100 setup scoring
      risk_reward/          entry / invalidation / R-multiple targets
      ai_analysis/          LLM interpretation + numeric-hallucination guard
      backtesting/          historical replay, no-lookahead-bias enforced
      reporting/            scheduled market report assembly
      scheduling/           Job/Scheduler abstraction (GitHub Actions today)
      database/             SQLAlchemy models + session
      schemas/              shared pydantic contracts between modules
    alembic/                database migrations
    tests/{unit,integration}
docs/decisions/     ADRs for non-obvious design decisions
```

## Getting started

### Backend (FastAPI)

```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../../.env.example .env   # then fill in DATABASE_URL / API keys
uvicorn app.main:app --reload
```

Run migrations once `DATABASE_URL` points at a reachable Postgres (a
Supabase project works with no local setup):

```bash
alembic upgrade head
```

Run tests and lint:

```bash
pytest
ruff check .
```

### Frontend (Next.js)

```bash
cd apps/web
npm install
cp ../../.env.example .env.local   # only NEXT_PUBLIC_API_URL is used here
npm run dev
```

Lint, typecheck, build:

```bash
npm run lint
npx tsc --noEmit
npm run build
```

## Status

Phases 1-10 are complete. Phases 1-5 built the market data engine, the
deterministic feature/market-structure/support-resistance engines (`GET
/api/market/{symbol}/{features,structure,levels}`), all under the same
`as_of`/no-lookahead discipline the rest of the pipeline reuses. Phase 6
added deterministic setup detection (13 detector modules covering all 16
`SetupType` values, `GET /api/market/{symbol}/setups`). Phase 7 added the
setup ledger and historical replay/outcome-evaluation engine
(`app/research/`). Phase 8 (ADR 0010) added the research-intelligence
statistics layer on top of it — baselines, bootstrap confidence intervals,
signal decay, excursion analysis, temporal/cross-symbol stability, a
deterministic historical analog engine, evidence cards, and research
snapshots (`/api/research/*`). Phase 9 (ADR 0012) added an independence/
robustness validation layer (episode grouping, purged sampling, block
bootstrap, walk-forward validation, conclusion stability) and, having
re-evaluated Phase 8's findings against it, reached an explicit **RANKING
GATE: FAIL** — evidence does not yet justify a calibrated, scored ranking
engine, and no such engine has been built.

Phase 10 (ADR 0013) added a News & Catalyst Context Engine: a
provider-independent news ingestion layer (fixture provider for tests, a
yfinance dev/research-only provider with real-data-verified normalization),
a deterministic 25-category catalyst taxonomy and event grouping/
deduplication, a market-reaction engine reusing Phase 7's own horizon/
excursion machinery, deterministic catalyst-to-setup linking (a six-label
descriptive vocabulary, never a buy/sell signal), additive extensions to
the Phase 8/9 cohort and historical-analog engines, and dashboard surfaces
("What's Moving the Market," a per-symbol catalyst timeline, and a Catalyst
Context section on every setup card) — see `/api/news/*` and
`/api/catalysts/*`. `scoring/`, `risk_reward/`, `ai_analysis/`,
`backtesting/`, and `reporting/` remain unimplemented placeholder packages;
see `docs/decisions/` and commit history for what's landed phase by phase.

## Development rules this project follows

- Deterministic financial calculations never come from the LLM.
- Every module boundary is a strict schema (pydantic), not a loose dict.
- No API keys in source code — environment variables only, see `.env.example`.
- No future candles during backtesting (no lookahead bias).
- Every generated setup/prediction is saved and later graded against real
  market data — this is how the scoring model gets validated or discarded.
