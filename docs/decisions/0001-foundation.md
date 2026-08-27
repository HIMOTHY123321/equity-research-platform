# ADR 0001: Foundation decisions

## Deterministic/AI boundary

Everything left of `ai_analysis` in the pipeline (market_data → features →
market_structure → support_resistance → setup_detection → scoring →
risk_reward) is plain Python: pandas/numpy, unit-tested, no LLM calls. The AI
analysis engine (Phase 9) receives only numbers these modules already
computed and must return structured JSON; any price/level in its response
that doesn't match a value the deterministic layer produced is rejected
before it reaches the database. This boundary is the reason `ai_analysis` is
a separate module rather than folded into scoring or reporting.

## Database

Postgres via a plain `DATABASE_URL`, so either a local Postgres or Supabase
works without code changes. SQLAlchemy 2.0 (typed `Mapped[...]` models) +
Alembic for migrations. The initial schema (`alembic/versions/0001_initial_schema.py`)
was hand-authored from `app/database/models.py` — a live database wasn't
available in the dev environment to run `alembic revision --autogenerate`
against, so the DDL was generated once via SQLAlchemy's own DDL compiler
(no connection required) and pinned into a migration. Future schema changes
should use `alembic revision --autogenerate` normally once a database is
reachable.

## Python 3.9 target

The development environment only has Python 3.9.6 available (no Homebrew,
pyenv, or Docker to get a newer interpreter). This has one concrete
consequence: PEP 604 union syntax (`X | None`) is written in source but
SQLAlchemy's declarative mapper evaluates model annotations at runtime and
`X | None` raises `TypeError` on 3.9. `app/database/models.py` therefore uses
`typing.Optional[X]` instead, and ruff's `UP007`/`UP037` (which would rewrite
this back to `X | None`) are disabled for this project. If the deployment
target moves to Python 3.10+, this restriction can be lifted.

## Candle contract

`app/schemas/market_data.py` defines the one normalized candle shape
(`symbol`, `timeframe`, `timestamp`, `open`, `high`, `low`, `close`,
`volume`) that every market-data source must be adapted into before
anything downstream touches it. It's a frozen, self-validating pydantic
model (rejects OHLC values that are internally inconsistent, negative
volume) so malformed bars fail loudly at the boundary instead of silently
propagating into indicators.
