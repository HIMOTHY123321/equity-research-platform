import pytest

from app.api import deps
from app.config import Settings
from app.market_data.alpaca_provider import AlpacaMarketDataProvider
from app.market_data.hybrid_provider import HybridMarketDataProvider
from app.market_data.twelve_data_provider import TwelveDataMarketDataProvider
from app.market_data.yfinance_provider import YFinanceMarketDataProvider


def test_default_provider_is_yfinance(monkeypatch):
    # _env_file=None: this asserts Settings' DEFAULT, which must never
    # depend on whatever MARKET_DATA_PROVIDER happens to be set to in the
    # developer's real local apps/api/.env (e.g. "hybrid").
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(_env_file=None))
    assert isinstance(deps._build_inner_provider(), YFinanceMarketDataProvider)


def test_provider_can_be_switched_to_alpaca_via_config(monkeypatch):
    monkeypatch.setattr(
        deps, "get_settings", lambda: Settings(_env_file=None, market_data_provider="alpaca")
    )
    assert isinstance(deps._build_inner_provider(), AlpacaMarketDataProvider)


def test_provider_selection_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        deps, "get_settings", lambda: Settings(_env_file=None, market_data_provider="ALPACA")
    )
    assert isinstance(deps._build_inner_provider(), AlpacaMarketDataProvider)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(
        deps, "get_settings", lambda: Settings(_env_file=None, market_data_provider="polygon")
    )
    with pytest.raises(ValueError, match="Unknown MARKET_DATA_PROVIDER"):
        deps._build_inner_provider()


def test_provider_can_be_switched_to_twelve_data_via_config(monkeypatch):
    monkeypatch.setattr(
        deps, "get_settings", lambda: Settings(_env_file=None, market_data_provider="twelve_data")
    )
    provider = deps._build_inner_provider()
    try:
        assert isinstance(provider, TwelveDataMarketDataProvider)
    finally:
        provider.close()


def test_get_streaming_provider_is_none_for_twelve_data_without_a_key(monkeypatch):
    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: Settings(_env_file=None, market_data_provider="twelve_data", twelve_data_api_key=""),
    )
    deps.get_streaming_provider.cache_clear()
    try:
        assert deps.get_streaming_provider() is None
    finally:
        deps.get_streaming_provider.cache_clear()


def test_get_streaming_provider_returns_twelve_data_streaming_when_key_configured(monkeypatch):
    from app.market_data.twelve_data_streaming import TwelveDataStreamingProvider

    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: Settings(
            _env_file=None, market_data_provider="twelve_data", twelve_data_api_key="test-key"
        ),
    )
    deps.get_streaming_provider.cache_clear()
    try:
        provider = deps.get_streaming_provider()
        assert isinstance(provider, TwelveDataStreamingProvider)
    finally:
        deps.get_streaming_provider.cache_clear()


def test_get_market_data_entitlement_routes_twelve_data_to_its_own_key(monkeypatch):
    from app.live.entitlement import EntitlementStatus

    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: Settings(
            _env_file=None, market_data_provider="twelve_data", twelve_data_api_key="test-key"
        ),
    )
    deps.get_market_data_entitlement.cache_clear()
    try:
        entitlement = deps.get_market_data_entitlement()
        assert entitlement.provider == "twelve_data"
        # Never blindly ENTITLED from a configured key alone.
        assert entitlement.status == EntitlementStatus.UNKNOWN
    finally:
        deps.get_market_data_entitlement.cache_clear()


def test_provider_can_be_switched_to_hybrid_via_config(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(_env_file=None, market_data_provider="hybrid"))
    provider = deps._build_inner_provider()
    assert isinstance(provider, HybridMarketDataProvider)


def test_get_streaming_provider_is_none_for_hybrid_without_a_key(monkeypatch):
    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: Settings(_env_file=None, market_data_provider="hybrid", twelve_data_api_key=""),
    )
    deps.get_streaming_provider.cache_clear()
    try:
        assert deps.get_streaming_provider() is None
    finally:
        deps.get_streaming_provider.cache_clear()


def test_get_streaming_provider_returns_twelve_data_streaming_for_hybrid_when_key_configured(monkeypatch):
    from app.market_data.twelve_data_streaming import TwelveDataStreamingProvider

    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: Settings(_env_file=None, market_data_provider="hybrid", twelve_data_api_key="test-key"),
    )
    deps.get_streaming_provider.cache_clear()
    try:
        provider = deps.get_streaming_provider()
        assert isinstance(provider, TwelveDataStreamingProvider)
    finally:
        deps.get_streaming_provider.cache_clear()


def test_get_market_data_entitlement_routes_hybrid_to_twelve_data_key(monkeypatch):
    from app.live.entitlement import EntitlementStatus

    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: Settings(_env_file=None, market_data_provider="hybrid", twelve_data_api_key="test-key"),
    )
    deps.get_market_data_entitlement.cache_clear()
    try:
        entitlement = deps.get_market_data_entitlement()
        assert entitlement.provider == "hybrid"
        assert entitlement.status == EntitlementStatus.UNKNOWN
    finally:
        deps.get_market_data_entitlement.cache_clear()
