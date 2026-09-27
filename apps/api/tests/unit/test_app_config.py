"""Phase 16 (§2/§3): production configuration must fail fast rather than
silently fall back to development-shaped defaults (SQLite, yfinance, an
empty signing secret, wildcard CORS)."""

from __future__ import annotations

import pytest

from app.config import ConfigurationError, Environment, Settings


def _base_production_kwargs() -> dict:
    return dict(
        environment=Environment.PRODUCTION,
        secret_key="a-real-signing-secret",
        database_url="postgresql+psycopg://user:pass@host:5432/db",
        market_data_provider="alpaca",
        news_provider="fixture",
        cors_origins="https://app.example.com",
    )


def test_production_with_full_safe_configuration_starts_cleanly():
    settings = Settings(_env_file=None, **_base_production_kwargs())
    assert settings.is_production is True


def test_development_defaults_never_raise():
    settings = Settings(_env_file=None)
    assert settings.environment == Environment.DEVELOPMENT
    assert settings.is_production is False


def test_production_rejects_missing_secret_key():
    kwargs = _base_production_kwargs()
    kwargs["secret_key"] = ""
    with pytest.raises(ConfigurationError, match="SECRET_KEY"):
        Settings(_env_file=None, **kwargs)


def test_production_rejects_the_development_placeholder_secret_key():
    kwargs = _base_production_kwargs()
    kwargs["secret_key"] = "insecure-development-secret-do-not-use-in-production"
    with pytest.raises(ConfigurationError, match="SECRET_KEY"):
        Settings(_env_file=None, **kwargs)


def test_production_rejects_sqlite_database():
    kwargs = _base_production_kwargs()
    kwargs["database_url"] = "sqlite:///./prod.db"
    with pytest.raises(ConfigurationError, match="SQLite"):
        Settings(_env_file=None, **kwargs)


def test_production_rejects_yfinance_market_data_provider():
    kwargs = _base_production_kwargs()
    kwargs["market_data_provider"] = "yfinance"
    with pytest.raises(ConfigurationError, match="MARKET_DATA_PROVIDER"):
        Settings(_env_file=None, **kwargs)


def test_production_rejects_yfinance_news_provider():
    kwargs = _base_production_kwargs()
    kwargs["news_provider"] = "yfinance"
    with pytest.raises(ConfigurationError, match="NEWS_PROVIDER"):
        Settings(_env_file=None, **kwargs)


def test_production_rejects_wildcard_cors():
    kwargs = _base_production_kwargs()
    kwargs["cors_origins"] = "*"
    with pytest.raises(ConfigurationError, match="CORS_ORIGINS"):
        Settings(_env_file=None, **kwargs)


def test_production_reports_every_problem_at_once():
    settings_kwargs = dict(
        environment=Environment.PRODUCTION,
        secret_key="",
        database_url="sqlite:///./prod.db",
        market_data_provider="yfinance",
        news_provider="yfinance",
        cors_origins="*",
    )
    with pytest.raises(ConfigurationError) as excinfo:
        Settings(_env_file=None, **settings_kwargs)
    message = str(excinfo.value)
    for expected in ("SECRET_KEY", "SQLite", "MARKET_DATA_PROVIDER", "NEWS_PROVIDER", "CORS_ORIGINS"):
        assert expected in message
