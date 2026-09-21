"""Phase 12.1 (#H/#Y): the live event vocabulary. Every event the WebSocket
route and the recomputation engine react to is one of these -- a closed,
typed set, same "no ad hoc dict payloads" discipline every other schema
boundary in this codebase follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from app.live.schemas import ConnectionStatus, LiveCandle, LiveQuote


@dataclass(frozen=True)
class QuoteEvent:
    symbol: str
    quote: LiveQuote


@dataclass(frozen=True)
class FormingCandleEvent:
    symbol: str
    candle: LiveCandle


@dataclass(frozen=True)
class CompletedCandleEvent:
    symbol: str
    candle: LiveCandle


@dataclass(frozen=True)
class ConnectionStatusEvent:
    status: ConnectionStatus


LiveEvent = Union[QuoteEvent, FormingCandleEvent, CompletedCandleEvent, ConnectionStatusEvent]
