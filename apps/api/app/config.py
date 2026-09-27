"""Central application configuration, loaded from environment variables.

No secrets are hard-coded here. Every value has a name matching .env.example.

Phase 16 (§2/§3): `environment` is now a closed enum, not a free string, and
`Settings` fails FAST at startup (raising out of `get_settings()`, which
FastAPI's lifespan calls before the app can serve a single request) when
`environment=production` is combined with configuration that would be
silently unsafe in production -- a missing signing secret, a SQLite
database URL, or a yfinance market/news provider (§35: yfinance is a
development/research fallback only, never a silent commercial production
feed). Development and test may use every one of those defaults freely;
production must say so explicitly by configuring real values, never by
inference from "looks like localhost."
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class ConfigurationError(RuntimeError):
    """Raised by Settings validation when environment=production is paired
    with configuration that would be unsafe to serve traffic with. Never
    caught and silently downgraded -- the app must not start."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    environment: Environment = Environment.DEVELOPMENT
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"

    # Phase 16 (§8/§28/§29): which half of the process this is.
    # "combined" (default) -- one process runs the HTTP API AND every
    #   background monitor (LiveMarketService/RecomputationEngine/
    #   ForecastMonitor/NewsMonitor/MonitoringService), exactly the
    #   pre-Phase-16 behavior -- correct for local dev/test and for a
    #   single-instance deployment, but WRONG for >1 web replica (every
    #   replica would independently run its own copy of every global
    #   monitor, duplicating work and duplicate-scanning the same symbols).
    # "api" -- HTTP routes only; background monitors are constructed (so
    #   status endpoints still have something to read) but never started.
    # "worker" -- background monitors run, but this replica need not
    #   receive user traffic; the recommended way to run a worker is the
    #   standalone `python -m app.worker` entrypoint (no FastAPI app at
    #   all), but the flag also works if a health-check-only web process
    #   is preferred instead.
    # Multi-replica web deployments MUST set every web replica to "api" and
    #   run exactly one separate "worker" process/replica -- see
    #   docs/deployment.md.
    worker_mode: str = "combined"

    # Signing key for JWT session tokens (Phase 16 §12/§14). PyJWT refuses
    # to sign with an empty key, so development/test get an obviously-fake
    # placeholder rather than "" -- the production validator below rejects
    # this exact placeholder (not just emptiness), so a deployer who
    # forgets to override it in production still fails fast instead of
    # accidentally shipping with a publicly-known signing secret.
    secret_key: str = "insecure-development-secret-do-not-use-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 24

    # Database. Defaults to a local SQLite file so Phase 7 (research-run
    # persistence) works out of the box with no paid service or local
    # Postgres install -- override with a Postgres/Supabase URL for anything
    # beyond solo local development. The Phase 7 research tables are written
    # to be portable across both dialects (see app/database/models.py); the
    # Phase 1 tables predate that and are Postgres-only -- see
    # docs/decisions/0008-setup-ledger-and-replay-engine.md for why they're
    # left as-is rather than retrofitted. This is the only place a database
    # path is ever named.
    database_url: str = "sqlite:///./ai_market_desk.db"

    # Market data provider selection: "yfinance" (default -- no account/key
    # needed, research/development only), "alpaca" (requires an eligible
    # account holder's API credentials below), or "massive" (Phase 12.2 --
    # requires massive_api_key below; the only provider in this codebase
    # that genuinely pushes trades/quotes/aggregates over a persistent
    # WebSocket rather than being polled). Never hard-code a choice
    # elsewhere in the codebase -- always branch on this setting.
    market_data_provider: str = "yfinance"

    # News/catalyst provider selection (Phase 10): "yfinance" (default --
    # no account/key needed, DEVELOPMENT/RESEARCH ONLY, see
    # app/news/yfinance_provider.py and docs/decisions/0013) or "fixture"
    # (deterministic, empty unless seeded -- tests only). A commercial
    # deployment needs a properly licensed news provider implementing
    # app.news.provider.NewsProvider; never hard-code a choice elsewhere.
    news_provider: str = "yfinance"

    # Alpaca Market Data
    alpaca_api_key_id: str = ""
    alpaca_api_secret_key: str = ""
    alpaca_data_base_url: str = "https://data.alpaca.markets"
    alpaca_paper: bool = True

    # Massive Market Data (Phase 12.2, only used when
    # MARKET_DATA_PROVIDER=massive). A missing key is never an error: the
    # app still starts, REST calls simply fail with AuthenticationError
    # (surfaced the same as any other provider outage), and
    # app.api.deps.get_streaming_provider() returns None so
    # LiveMarketService falls back to its existing per-symbol poll loop --
    # see docs/decisions/0018-streaming-market-data-provider.md. The key is
    # never sent to the browser; only this backend process ever holds it.
    massive_api_key: str = ""
    massive_rest_base_url: str = "https://api.massive.com"
    massive_ws_url: str = "wss://socket.massive.com/stocks"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # AI Research Analyst provider selection (Phase 11): "mock" (default --
    # deterministic, no credentials needed, used by every test) or "openai"
    # (development-only real-model synthesis; requires openai_api_key).
    # Every AI-provider output is independently grounded/validated
    # (app.ai_analysis.validation) regardless of which provider produced it
    # -- never hard-code a choice elsewhere in the codebase.
    ai_analysis_provider: str = "mock"

    # Scheduling
    scheduler_shared_secret: str = ""
    report_timezone: str = "America/New_York"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def runs_background_workers(self) -> bool:
        """Phase 16 (§8/§28/§29): whether THIS process should start the
        global background monitors (see app.main.lifespan / app.worker) --
        pulled out as its own testable property rather than inlined at the
        lifespan call site, since the module-level `settings` object in
        app.main is constructed once at import time and hard to
        re-parametrize per-test."""
        return self.worker_mode in ("combined", "worker")

    @model_validator(mode="after")
    def _validate_production_safety(self) -> "Settings":
        if self.environment != Environment.PRODUCTION:
            return self

        problems: list[str] = []
        if not self.secret_key or self.secret_key == "insecure-development-secret-do-not-use-in-production":
            problems.append(
                "SECRET_KEY is required in production and must not be the development "
                "placeholder (session signing key)"
            )
        if self.database_url.startswith("sqlite"):
            problems.append(
                "DATABASE_URL must not be SQLite in production -- SQLite is a "
                "development/test convenience only (see docs/decisions for the Postgres "
                "production database architecture)"
            )
        if self.market_data_provider == "yfinance":
            problems.append(
                "MARKET_DATA_PROVIDER must not be 'yfinance' in production -- yfinance is a "
                "development/research fallback, never a licensed commercial feed. Configure "
                "'alpaca' or 'massive' with real credentials, or run with market data "
                "explicitly in a degraded/unavailable state rather than a silent fallback."
            )
        if self.news_provider == "yfinance":
            problems.append(
                "NEWS_PROVIDER must not be 'yfinance' in production -- it is development/"
                "research only. Configure a properly licensed news provider."
            )
        if self.cors_origins.strip() in ("", "*"):
            problems.append("CORS_ORIGINS must be an explicit origin list in production, never '*'")

        if problems:
            raise ConfigurationError(
                "Refusing to start with environment=production and unsafe configuration:\n- "
                + "\n- ".join(problems)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
