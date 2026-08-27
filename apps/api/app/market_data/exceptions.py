"""Errors raised by market data providers. Routes map these to HTTP responses."""

from __future__ import annotations


class MarketDataError(Exception):
    """Base class for all market-data provider errors."""


class AuthenticationError(MarketDataError):
    """Credentials were rejected (401/403). Never retried — a retry can't fix a bad key."""


class RateLimitError(MarketDataError):
    """The provider rate-limited us (429) after retries were exhausted."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderError(MarketDataError):
    """Upstream error (5xx, network failure, or unparseable response) after retries."""


class InvalidSymbolError(MarketDataError):
    """The provider does not recognize this symbol."""

    def __init__(self, symbol: str) -> None:
        super().__init__(f"Unknown symbol: {symbol}")
        self.symbol = symbol
