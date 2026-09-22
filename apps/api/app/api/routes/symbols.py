"""SymbolSearch routes (MARKET UX COMPLETION PASS #3/#4). Every route here
depends only on `SymbolDirectory` (never `StaticSymbolDirectory` directly),
so swapping in a licensed reference-data source later is a one-line change
in `deps.py`, not a route rewrite.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.symbols.directory import SymbolDirectory
from app.symbols.schemas import SymbolMatch, SymbolSearchResponse
from app.symbols.static_directory import DEFAULT_SYMBOL_DIRECTORY

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


def get_symbol_directory() -> SymbolDirectory:
    return DEFAULT_SYMBOL_DIRECTORY


@router.get("/search", response_model=SymbolSearchResponse)
def search_symbols(
    q: str = Query(..., min_length=1, max_length=64),
    watchlist: str = Query("", description="Comma-separated tickers to rank first among ties"),
    limit: int = Query(10, ge=1, le=50),
    directory: SymbolDirectory = Depends(get_symbol_directory),
) -> SymbolSearchResponse:
    watchlist_tickers = [t.strip().upper() for t in watchlist.split(",") if t.strip()]
    results = directory.search(q, watchlist_tickers=watchlist_tickers, limit=limit)
    return SymbolSearchResponse(query=q, results=results)


@router.get("/{ticker}", response_model=SymbolMatch)
def get_symbol(
    ticker: str, directory: SymbolDirectory = Depends(get_symbol_directory)
) -> SymbolMatch:
    match = directory.get(ticker)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    return match
