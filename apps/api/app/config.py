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
from typing import Optional

from pydantic import field_validator, model_validator
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
    #
    # Phase 19.1: `SECRET_KEY=` present-but-blank in a local `.env` (the
    # same "leave unset" shape as MASSIVE_STREAMING_ENTITLED=) previously
    # meant pydantic-settings loaded `secret_key=""` -- a valid string, so
    # no validation error at startup, but every JWT signing call then
    # raised `InvalidKeyError: HMAC key must not be empty` at request time.
    # Empty resolves to the safe development placeholder below instead;
    # production's own validator still correctly rejects that exact
    # placeholder, so this never weakens the production requirement for a
    # real, explicitly-configured secret.
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
    # account holder's API credentials below), "massive" (Phase 12.2 --
    # requires massive_api_key below; genuinely pushes trades/quotes/
    # aggregates over a persistent WebSocket), "twelve_data" (Phase 19.1 --
    # requires twelve_data_api_key below; a free-tier-friendly REST +
    # trial-WebSocket provider whose actual streaming entitlement is
    # discovered at runtime from subscription acknowledgements, never
    # assumed from a configured key -- see app.live.entitlement and
    # app.market_data.twelve_data_streaming), or "hybrid" (Phase 19.2 --
    # Twelve Data for genuine live/latest quotes + WebSocket streaming,
    # yfinance for ALL historical/research candles and as the REST
    # fallback when Twelve Data is rate-limited/unavailable; see
    # app.market_data.hybrid_provider for the exact split and
    # docs/decisions for why yfinance alone was never safe to drop
    # entirely once free-tier REST credits are the only Twelve Data
    # budget). Never hard-code a choice elsewhere in the codebase --
    # always branch on this setting.
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

    # Phase 17 (§1/§27/§75): explicit, operator-set confirmation that the
    # configured Massive account actually carries real-time streaming
    # entitlement -- Massive's API exposes no "what tier is this key"
    # call, so a valid key alone is NEVER treated as proof (see
    # app.live.entitlement). None (default, unset) means UNKNOWN, not
    # "assume yes." Only an explicit true/false here can produce
    # ENTITLED/NOT_ENTITLED.
    massive_streaming_entitled: Optional[bool] = None

    # Twelve Data Market Data (Phase 19.1, only used when
    # MARKET_DATA_PROVIDER=twelve_data). Unlike Massive, there is
    # deliberately NO "twelve_data_streaming_entitled" boolean here -- a
    # free/Basic-plan API key proves nothing about which symbols (if any)
    # genuinely carry trial WebSocket access, and Twelve Data's own API
    # exposes no "what tier is this key" call either. Entitlement is
    # instead discovered honestly at runtime from the WebSocket's own
    # subscribe-status acknowledgements (see app.live.entitlement and
    # app.market_data.twelve_data_streaming.TwelveDataStreamingProvider.
    # entitlement_hint) -- never a blind operator switch. A missing key is
    # never a startup error: REST calls simply fail with
    # AuthenticationError, and get_streaming_provider() returns None so
    # LiveMarketService falls back to REST polling, exactly like Massive.
    # The key is never sent to the browser; only this backend process ever
    # holds it, and it is never written to a log line or exception message.
    twelve_data_api_key: str = ""
    twelve_data_rest_base_url: str = "https://api.twelvedata.com"
    twelve_data_ws_base_url: str = "wss://ws.twelvedata.com"

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

    # Phase 17 (§60/§79/§99): a deterministic, fully-scripted streaming
    # provider (app.live.mock_streaming.MockStreamingProvider) a developer
    # can drive by hand via /api/dev/live-simulator to preview live-chart
    # UX without any real provider account. False by default even in
    # development -- opting in is a conscious choice, not an ambient
    # default -- and the production validator below makes it structurally
    # impossible to enable in production, not just discouraged.
    enable_dev_live_simulator: bool = False

    # Phase 20/20.1: Pushover phone-notification delivery (app.alerts.push).
    # `pushover_app_token` identifies THIS application to Pushover's API --
    # it is genuinely shared/global, the same way a Twilio account SID would
    # be. There is deliberately NO global `pushover_user_key` setting: in a
    # multi-user product, a single global destination key would mean every
    # user's alerts ring the SAME phone, which is a real cross-user data
    # leak, not just a config inconvenience. Each user who opts in stores
    # their OWN Pushover User Key, encrypted at rest (see
    # app.notifications.secret_crypto and
    # UserPushPreferenceRecord.pushover_user_key_encrypted) -- push is
    # dispatched separately to each eligible user's own key, never a shared
    # one. Missing the app token or the global enable flag is never a
    # startup error, it just means push dispatch silently no-ops (same
    # "absence is not an error" convention as twelve_data_api_key above).
    # The app token is never sent to the browser, logged, or included in an
    # exception message; only this backend process ever holds it.
    push_notifications_enabled: bool = False
    pushover_app_token: str = ""

    # Phase 20.2: the DEDICATED key used to encrypt/decrypt per-user
    # Pushover destination keys at rest (app.notifications.secret_crypto).
    # Deliberately separate from `secret_key` (the JWT/session signing
    # secret): rotating SECRET_KEY is an ordinary, expected session-
    # security operation and must never silently make every already-
    # stored Pushover user key undecryptable as a side effect. May be
    # either a real `Fernet.generate_key()` value or any other non-empty
    # string (safely transformed into a Fernet key either way -- see
    # secret_crypto._coerce_fernet_key). Missing is never a startup error
    # -- push dispatch and the push-key endpoints simply treat push as
    # unconfigured (see app.alerts.push and app.api.routes.alerts), the
    # same "absence degrades, never crashes" convention every other
    # optional provider credential in this file follows. Never sent to
    # the browser, logged, or included in an exception message.
    pushover_key_encryption_key: str = ""

    # Long-Term Investing Research scan (app.long_term_research) -- a
    # feature wholly separate from the Decision Engine. "yfinance"
    # (default -- no account/key needed, research/development only,
    # same caveat as market_data_provider's own yfinance option) or
    # "fixture" (deterministic, empty unless seeded -- tests only).
    fundamentals_provider: str = "yfinance"

    # Shared secret the externally (cron-)triggered scheduled scan
    # endpoint requires in its `X-Scheduler-Secret` header -- see
    # app.api.routes.long_term_research. Reuses the SAME
    # `scheduler_shared_secret` setting already reserved above for
    # exactly this kind of externally-triggered-endpoint authentication
    # (it was never wired to anything before this feature). An empty
    # value (the default) means the scheduled-scan endpoint always
    # rejects every request -- there is no "secret not configured, so
    # allow anyone" fallback.

    @field_validator("secret_key", mode="before")
    @classmethod
    def _blank_secret_key_means_unset(cls, value):
        """See this field's own docstring above -- `SECRET_KEY=` (present,
        empty) must behave identically to the variable being absent
        entirely (falls back to the safe development placeholder), never
        silently loaded as an empty string that only breaks at first JWT
        signing. Any non-empty string is passed through unchanged."""
        if isinstance(value, str) and value.strip() == "":
            return "insecure-development-secret-do-not-use-in-production"
        return value

    @field_validator("massive_streaming_entitled", mode="before")
    @classmethod
    def _blank_massive_streaming_entitled_means_unset(cls, value):
        """An `.env` line like `MASSIVE_STREAMING_ENTITLED=` (present but
        empty -- the documented "leave unset" convention this file's own
        .env.example/docs/deployment.md instructions describe) must mean
        None/UNKNOWN, not a pydantic bool-parsing crash that prevents the
        app from starting at all. Any non-empty string is passed through
        unchanged for pydantic's own bool coercion to handle."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

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
                "'alpaca', 'massive', 'twelve_data', or 'hybrid' with real credentials, or run with "
                "market data explicitly in a degraded/unavailable state rather than a silent "
                "fallback."
            )
        if self.news_provider == "yfinance":
            problems.append(
                "NEWS_PROVIDER must not be 'yfinance' in production -- it is development/"
                "research only. Configure a properly licensed news provider."
            )
        if self.cors_origins.strip() in ("", "*"):
            problems.append("CORS_ORIGINS must be an explicit origin list in production, never '*'")
        if self.enable_dev_live_simulator:
            problems.append(
                "ENABLE_DEV_LIVE_SIMULATOR must not be true in production -- the mock streaming "
                "simulator is a development-only tool for previewing live-chart UX with synthetic "
                "data, never a real market data source"
            )

        if problems:
            raise ConfigurationError(
                "Refusing to start with environment=production and unsafe configuration:\n- "
                + "\n- ".join(problems)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
