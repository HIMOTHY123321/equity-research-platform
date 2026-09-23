"""Response envelopes for the market-data API routes."""

from typing import Optional

from pydantic import BaseModel

from app.schemas.market_data import Candle, PreviousClose, Quote


class CandlesResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: list[Candle]
    # (FINAL TERMINAL POLISH PASS #1: lazy pan-left pagination) `has_more`
    # is true only when this exact chunk came back full (== the requested
    # `limit`) -- a short chunk is honest provider-side history exhaustion,
    # never a guess. `next_before` is the oldest returned candle's own
    # timestamp, the cursor a follow-up request must pass as `before` to
    # continue paginating without re-fetching or skipping a candle.
    has_more: bool = False
    history_exhausted: bool = False
    next_before: Optional[str] = None


class SymbolQuoteResponse(BaseModel):
    symbol: str
    quote: Quote
    previous_close: PreviousClose
    today: Optional[Candle] = None
