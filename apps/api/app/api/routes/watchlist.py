from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_watchlist_repository
from app.schemas.symbols import InvalidTickerError
from app.schemas.watchlist import AddWatchlistSymbolRequest, WatchlistSymbolOut
from app.watchlist.repository import (
    SymbolAlreadyInWatchlistError,
    SymbolNotInWatchlistError,
    WatchlistRepository,
)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistSymbolOut])
def list_watchlist(
    repo: WatchlistRepository = Depends(get_watchlist_repository),
) -> list[WatchlistSymbolOut]:
    return [WatchlistSymbolOut(ticker=e.ticker, added_at=e.added_at) for e in repo.list_symbols()]


@router.post("/symbols", response_model=WatchlistSymbolOut, status_code=201)
def add_symbol(
    payload: AddWatchlistSymbolRequest,
    repo: WatchlistRepository = Depends(get_watchlist_repository),
) -> WatchlistSymbolOut:
    try:
        entry = repo.add_symbol(payload.ticker)
    except InvalidTickerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SymbolAlreadyInWatchlistError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WatchlistSymbolOut(ticker=entry.ticker, added_at=entry.added_at)


@router.delete("/symbols/{symbol}", status_code=204, response_model=None)
def remove_symbol(
    symbol: str,
    repo: WatchlistRepository = Depends(get_watchlist_repository),
) -> None:
    try:
        repo.remove_symbol(symbol)
    except InvalidTickerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SymbolNotInWatchlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
