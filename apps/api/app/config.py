"""Central application configuration, loaded from environment variables.

No secrets are hard-coded here. Every value has a name matching .env.example.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
