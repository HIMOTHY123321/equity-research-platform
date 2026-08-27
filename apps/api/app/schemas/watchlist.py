from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WatchlistSymbolOut(BaseModel):
    ticker: str
    added_at: datetime


class AddWatchlistSymbolRequest(BaseModel):
    ticker: str
