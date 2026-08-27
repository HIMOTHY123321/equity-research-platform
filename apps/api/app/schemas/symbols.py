"""Shared ticker validation, used by both the watchlist and market-data routes."""

from __future__ import annotations

import re

# Plain US equity tickers (1-5 letters) plus the "BRK.A"-style share-class suffix.
TICKER_PATTERN = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


class InvalidTickerError(ValueError):
    def __init__(self, raw: str) -> None:
        super().__init__(f"Invalid ticker symbol: {raw!r}")
        self.raw = raw


def normalize_ticker(raw: str) -> str:
    """Uppercase and validate a ticker. Raises InvalidTickerError if malformed."""
    ticker = raw.strip().upper()
    if not TICKER_PATTERN.match(ticker):
        raise InvalidTickerError(raw)
    return ticker
