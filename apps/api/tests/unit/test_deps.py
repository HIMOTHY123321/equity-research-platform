import pytest

from app.api import deps
from app.config import Settings
from app.market_data.alpaca_provider import AlpacaMarketDataProvider
from app.market_data.yfinance_provider import YFinanceMarketDataProvider


def test_default_provider_is_yfinance(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: Settings())
    assert isinstance(deps._build_inner_provider(), YFinanceMarketDataProvider)


def test_provider_can_be_switched_to_alpaca_via_config(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(market_data_provider="alpaca"))
    assert isinstance(deps._build_inner_provider(), AlpacaMarketDataProvider)


def test_provider_selection_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(market_data_provider="ALPACA"))
    assert isinstance(deps._build_inner_provider(), AlpacaMarketDataProvider)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(market_data_provider="polygon"))
    with pytest.raises(ValueError, match="Unknown MARKET_DATA_PROVIDER"):
        deps._build_inner_provider()
