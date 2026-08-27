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

Phases 1-5 are complete: project foundation, the market data engine
(`MarketDataProvider`/Alpaca, session-aware 4H aggregation, watchlist,
`/api/market/*` + `/api/watchlist/*`), the deterministic feature engine
(previous day/week levels, gap, Wilder ATR, EMA/SMA with distance-from-price,
rolling highs/lows, relative volume, latest-candle classification,
session-so-far range), the deterministic market structure engine
(swing high/low detection with an explicit `pivot_timestamp`/`confirmed_at`
split, HH/HL/LH/LL classification, trend classification, Break of Structure,
Change of Character, active range, freshness metrics, and multi-timeframe
summaries), and the deterministic, evidence-backed support/resistance
engine (multi-timeframe raw levels, percentage-tolerance clustering into
zones with full provenance, independent touch/rejection/break detection,
an explainable 0-100 strength score with diminishing returns, zone
lifecycle, and nearest-level helpers) — all under the same `as_of`/
no-lookahead discipline, safe for later reuse by the backtester.
`GET /api/market/{symbol}/features`, `/structure`, and `/levels` expose
these, and the dashboard shows a feature panel, a market structure panel,
and a support/resistance panel (with a "why this level?" evidence
breakdown) under the chart, which now also overlays swing/BOS/CHOCH
markers and support/resistance zone lines. No setup detection, scoring, or
AI calls are implemented yet — see `docs/decisions/` and commit history for
what's landed phase by phase.

## Development rules this project follows

- Deterministic financial calculations never come from the LLM.
- Every module boundary is a strict schema (pydantic), not a loose dict.
- No API keys in source code — environment variables only, see `.env.example`.
- No future candles during backtesting (no lookahead bias).
- Every generated setup/prediction is saved and later graded against real
  market data — this is how the scoring model gets validated or discarded.
