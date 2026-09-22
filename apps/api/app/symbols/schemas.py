"""SymbolSearch schemas (MARKET UX COMPLETION PASS #3). Deliberately small:
a search result is just enough to identify and display a symbol -- no
sector/exchange/market-cap metadata this codebase doesn't actually have a
real source for (never fabricated)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class AssetType(str, Enum):
    EQUITY = "equity"
    ETF = "etf"


class SymbolMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    name: str
    asset_type: AssetType
    # (#3) 1 = exact ticker, 2 = ticker prefix, 3 = company-name prefix,
    # 4 = company-name contains -- the UI can group/label by this without
    # re-deriving the match logic; never a fabricated relevance score.
    match_tier: int


class SymbolSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    results: list[SymbolMatch]
