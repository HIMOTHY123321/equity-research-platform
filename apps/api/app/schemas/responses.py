"""Response envelopes for the market-data API routes."""

from typing import Optional

from pydantic import BaseModel

from app.schemas.market_data import Candle, PreviousClose, Quote


class CandlesResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: list[Candle]


class SymbolQuoteResponse(BaseModel):
    symbol: str
    quote: Quote
    previous_close: PreviousClose
    today: Optional[Candle] = None
