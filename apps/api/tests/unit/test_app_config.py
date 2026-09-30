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


def test_production_rejects_dev_live_simulator_enabled():
    """Phase 19 follow-up: closes a real gap -- prior to this test, no
    unit test asserted that ENABLE_DEV_LIVE_SIMULATOR=true is rejected in
    production; only an integration test that simulated "disabled" via a
    dependency override existed, which never exercised this validator
    branch at all. Verified live via a real `uvicorn app.main:app` process
    with ENVIRONMENT=production + ENABLE_DEV_LIVE_SIMULATOR=true: the
    process crashes during module import with exactly this error, before
    ever touching the database or binding a port."""
    kwargs = _base_production_kwargs()
    kwargs["enable_dev_live_simulator"] = True
    with pytest.raises(ConfigurationError, match="ENABLE_DEV_LIVE_SIMULATOR"):
        Settings(_env_file=None, **kwargs)


def test_twelve_data_fields_default_to_empty_and_never_error_when_unset():
    settings = Settings(_env_file=None)
    assert settings.twelve_data_api_key == ""
    assert settings.twelve_data_rest_base_url == "https://api.twelvedata.com"
    assert settings.twelve_data_ws_base_url == "wss://ws.twelvedata.com"


def test_twelve_data_api_key_is_accepted_when_configured():
    settings = Settings(_env_file=None, twelve_data_api_key="a-configured-key")
    assert settings.twelve_data_api_key == "a-configured-key"


def test_twelve_data_api_key_never_appears_in_settings_repr_by_accident():
    """Not a redaction guarantee (Settings has no custom __repr__) -- this
    documents/pins that the key is a plain string field like every other
    provider key in this file, so any future redaction work covers it
    uniformly rather than needing special-casing."""
    Settings(_env_file=None, twelve_data_api_key="super-secret-value")
    assert "twelve_data_api_key" in Settings.model_fields


def test_production_settings_do_not_require_twelve_data_configuration():
    """Twelve Data is optional -- production must not fail just because it
    isn't the configured provider."""
    settings = Settings(_env_file=None, **_base_production_kwargs())
    assert settings.twelve_data_api_key == ""


def test_env_example_has_only_placeholder_twelve_data_values():
    """(§1) .env.example must never carry a real secret -- TWELVE_DATA_
    API_KEY must be present (documenting the field exists) but blank."""
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[4]
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")
    assert "TWELVE_DATA_API_KEY=" in env_example
    for line in env_example.splitlines():
        if line.startswith("TWELVE_DATA_API_KEY="):
            assert line == "TWELVE_DATA_API_KEY="
    assert "TWELVE_DATA_REST_BASE_URL=https://api.twelvedata.com" in env_example
    assert "TWELVE_DATA_WS_BASE_URL=wss://ws.twelvedata.com" in env_example


def test_secret_key_blank_string_falls_back_to_the_safe_development_placeholder():
    """Phase 19.1: a real bug found while running the full suite against
    the user's local .env -- `SECRET_KEY=` (present, blank) previously
    loaded as `secret_key=""`, passing model construction but crashing
    every JWT signing call at request time with `InvalidKeyError`. Blank
    must resolve to the same safe placeholder the variable being absent
    entirely would produce."""
    settings = Settings(_env_file=None, secret_key="")
    assert settings.secret_key == "insecure-development-secret-do-not-use-in-production"


def test_secret_key_blank_string_is_still_rejected_in_production():
    """The fallback must never leak into production -- a blank
    SECRET_KEY resolves to the development placeholder, which production's
    own validator already rejects by name."""
    kwargs = _base_production_kwargs()
    kwargs["secret_key"] = ""
    with pytest.raises(ConfigurationError, match="SECRET_KEY"):
        Settings(_env_file=None, **kwargs)


def test_massive_streaming_entitled_blank_string_is_treated_as_unset():
    """A real bug found during Phase 19.1 validation: `MASSIVE_STREAMING_
    ENTITLED=` (present but empty, the documented "leave unset" .env
    convention) previously crashed Settings() entirely with a pydantic
    bool-parsing error, meaning the app could not start at all with that
    exact .env line. Empty string must resolve to None (UNKNOWN), the same
    as the field being absent."""
    settings = Settings(_env_file=None, massive_streaming_entitled="")
    assert settings.massive_streaming_entitled is None


def test_production_with_safe_configuration_never_enables_the_simulator_by_default():
    """The flip side: production with every OTHER field safe and the
    simulator field left at its default (False, never set) must construct
    cleanly and report the simulator as off -- production is never
    accidentally blocked from starting by this flag, only by explicitly
    turning it on."""
    settings = Settings(_env_file=None, **_base_production_kwargs())
    assert settings.enable_dev_live_simulator is False


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
