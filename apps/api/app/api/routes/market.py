from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_market_data_provider
from app.features.engine import compute_feature_snapshot
from app.features.schemas import FeatureSnapshot
from app.market_data.provider import MarketDataProvider
from app.market_structure.engine import compute_market_structure_snapshot
from app.market_structure.schemas import MarketStructureSnapshot
from app.schemas.market_data import Timeframe
from app.schemas.responses import CandlesResponse, SymbolQuoteResponse
from app.schemas.symbols import InvalidTickerError, normalize_ticker
from app.setup_detection.schemas import SetupDetectionSnapshot
from app.support_resistance.engine import compute_support_resistance_snapshot
from app.support_resistance.schemas import SupportResistanceSnapshot

# History depth per timeframe. Chosen from real yfinance history-window
# limits observed during the Phase 5 real-data validation checkpoint (see
# docs/decisions/0006-yfinance-development-provider.md):
#   - 1d: essentially unlimited history available; 300 bars (~14 months)
#     comfortably covers SMA200 with buffer without over-fetching.
#   - 1h: yfinance allows ~730 days of history; 2000 bars (~120 trading
#     days) gives meaningful daily/4H-scale structure without pulling the
#     full 2 years on every request.
#   - 4h: this is the *4H bar count* requested; it drives how much
#     underlying 1H history the provider pulls internally (aggregation.py),
#     independent of the 1H row above.
#   - 15m/5m: yfinance caps at 60 calendar days total regardless of what we
#     ask for (~3776 / ~11326 bars respectively) -- request enough that we
#     always get everything Yahoo will give. This directly addresses the
#     Phase 3 note that a flat 300-bar limit was too thin for 20-day
#     intraday RVOL (300 5m bars is under 2 trading days).
CANDLE_LIMIT_BY_TIMEFRAME: dict[Timeframe, int] = {
    Timeframe.ONE_DAY: 300,
    Timeframe.FOUR_HOUR: 300,
    Timeframe.ONE_HOUR: 2000,
    Timeframe.FIFTEEN_MIN: 4000,
    Timeframe.FIVE_MIN: 12000,
    # 7 real calendar days at 1m resolution including extended hours (~600
    # min/day including pre/post-market) -- generous enough to always get
    # everything Yahoo's real 7-day 1m window will give, never a request
    # that silently truncates before that window's own limit does.
    Timeframe.ONE_MIN: 5000,
}

# S/R evidence always draws from these timeframes' confirmed swings,
# regardless of which timeframe interactions/breaks are evaluated against.
LEVEL_SOURCE_TIMEFRAMES = (Timeframe.ONE_DAY, Timeframe.FOUR_HOUR)

router = APIRouter(prefix="/api/market", tags=["market"])

# Only timeframes actually supported for fetching/constructing. 1w is
# defined in the internal Candle contract but not wired up yet.
ALLOWED_CANDLE_TIMEFRAMES = {
    Timeframe.ONE_MIN,
    Timeframe.FIVE_MIN,
    Timeframe.FIFTEEN_MIN,
    Timeframe.ONE_HOUR,
    Timeframe.FOUR_HOUR,
    Timeframe.ONE_DAY,
}


def _validated_symbol(symbol: str) -> str:
    try:
        return normalize_ticker(symbol)
    except InvalidTickerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validated_timeframe(timeframe: str) -> Timeframe:
    try:
        parsed = Timeframe(timeframe)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {timeframe!r}") from None
    if parsed not in ALLOWED_CANDLE_TIMEFRAMES:
        allowed = ", ".join(sorted(t.value for t in ALLOWED_CANDLE_TIMEFRAMES))
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported timeframe {timeframe!r} for this endpoint. Allowed: {allowed}",
        )
    return parsed


@router.get("/{symbol}/candles", response_model=CandlesResponse)
def get_candles(
    symbol: str,
    timeframe: str = Query("1d"),
    # Hardening pass (§6/§8), raised again in the MARKET EXPERIENCE
    # COMPLETION PASS (#6): a MAX-range daily chart must reach a symbol's
    # true earliest listing history (yfinance's period is now "max", not a
    # fixed "10y" -- see YFinanceMarketDataProvider/_YFINANCE_MAX_PERIOD),
    # and a long-lived symbol like SPY (trading since 1993) has ~8500+ daily
    # bars. 15000 gives headroom for that while staying explicitly bounded,
    # never "however many bars exist" -- see docs/decisions on avoiding
    # unbounded history payloads.
    limit: int = Query(200, ge=1, le=15000),
    provider: MarketDataProvider = Depends(get_market_data_provider),
) -> CandlesResponse:
    validated_symbol = _validated_symbol(symbol)
    validated_timeframe = _validated_timeframe(timeframe)
    candles = provider.get_candles(validated_symbol, validated_timeframe, limit=limit)
    return CandlesResponse(
        symbol=validated_symbol, timeframe=validated_timeframe.value, candles=candles
    )


@router.get("/{symbol}/quote", response_model=SymbolQuoteResponse)
def get_quote(
    symbol: str,
    provider: MarketDataProvider = Depends(get_market_data_provider),
) -> SymbolQuoteResponse:
    validated_symbol = _validated_symbol(symbol)
    quote = provider.get_latest_quote(validated_symbol)
    previous_close = provider.get_previous_close(validated_symbol)
    today_bars = provider.get_candles(validated_symbol, Timeframe.ONE_DAY, limit=1)
    today = today_bars[-1] if today_bars else None
    return SymbolQuoteResponse(
        symbol=validated_symbol, quote=quote, previous_close=previous_close, today=today
    )


@router.get("/{symbol}/features", response_model=FeatureSnapshot)
def get_features(
    symbol: str,
    timeframe: str = Query("1d"),
    provider: MarketDataProvider = Depends(get_market_data_provider),
) -> FeatureSnapshot:
    validated_symbol = _validated_symbol(symbol)
    validated_timeframe = _validated_timeframe(timeframe)
    as_of = datetime.now(timezone.utc)

    primary_candles = provider.get_candles(
        validated_symbol, validated_timeframe, limit=CANDLE_LIMIT_BY_TIMEFRAME[validated_timeframe]
    )
    if validated_timeframe == Timeframe.ONE_DAY:
        daily_candles = primary_candles
    else:
        daily_candles = provider.get_candles(
            validated_symbol, Timeframe.ONE_DAY, limit=CANDLE_LIMIT_BY_TIMEFRAME[Timeframe.ONE_DAY]
        )

    return compute_feature_snapshot(
        symbol=validated_symbol,
        timeframe=validated_timeframe,
        primary_candles=primary_candles,
        daily_candles=daily_candles,
        as_of=as_of,
    )


@router.get("/{symbol}/structure", response_model=MarketStructureSnapshot)
def get_structure(
    symbol: str,
    timeframe: str = Query("1h"),
    provider: MarketDataProvider = Depends(get_market_data_provider),
) -> MarketStructureSnapshot:
    validated_symbol = _validated_symbol(symbol)
    validated_timeframe = _validated_timeframe(timeframe)
    as_of = datetime.now(timezone.utc)

    candles = provider.get_candles(
        validated_symbol, validated_timeframe, limit=CANDLE_LIMIT_BY_TIMEFRAME[validated_timeframe]
    )

    return compute_market_structure_snapshot(
        symbol=validated_symbol,
        timeframe=validated_timeframe,
        candles=candles,
        as_of=as_of,
    )


class _CandleCache:
    """Per-request memoization so a candle/structure timeframe is ever
    fetched or computed once, shared between /levels and /setups since both
    need the same multi-timeframe structure context (#39). Deliberately
    just a dict-backed cache local to a single request -- not a general
    caching framework, and unrelated to CachedMarketDataProvider's
    cross-request TTL cache."""

    def __init__(self, provider: MarketDataProvider, symbol: str, as_of: datetime):
        self._provider = provider
        self._symbol = symbol
        self._as_of = as_of
        self._candles: dict[Timeframe, list] = {}
        self._structure: dict[Timeframe, MarketStructureSnapshot] = {}

    def candles(self, timeframe: Timeframe) -> list:
        if timeframe not in self._candles:
            self._candles[timeframe] = self._provider.get_candles(
                self._symbol, timeframe, limit=CANDLE_LIMIT_BY_TIMEFRAME[timeframe]
            )
        return self._candles[timeframe]

    def structure(self, timeframe: Timeframe) -> MarketStructureSnapshot:
        if timeframe not in self._structure:
            self._structure[timeframe] = compute_market_structure_snapshot(
                self._symbol, timeframe, self.candles(timeframe), self._as_of
            )
        return self._structure[timeframe]


@router.get("/{symbol}/levels", response_model=SupportResistanceSnapshot)
def get_levels(
    symbol: str,
    timeframe: str = Query("1h"),
    provider: MarketDataProvider = Depends(get_market_data_provider),
) -> SupportResistanceSnapshot:
    validated_symbol = _validated_symbol(symbol)
    validated_timeframe = _validated_timeframe(timeframe)
    as_of = datetime.now(timezone.utc)
    cache = _CandleCache(provider, validated_symbol, as_of)

    daily_candles = cache.candles(Timeframe.ONE_DAY)
    primary_candles = cache.candles(validated_timeframe)

    source_timeframes = set(LEVEL_SOURCE_TIMEFRAMES) | {validated_timeframe}
    structure_snapshots = {tf: cache.structure(tf) for tf in source_timeframes}

    return compute_support_resistance_snapshot(
        symbol=validated_symbol,
        timeframe=validated_timeframe,
        primary_candles=primary_candles,
        daily_candles=daily_candles,
        structure_snapshots=structure_snapshots,
        as_of=as_of,
    )


@router.get("/{symbol}/setups", response_model=SetupDetectionSnapshot)
def get_setups(
    symbol: str,
    timeframe: str = Query("1h"),
    provider: MarketDataProvider = Depends(get_market_data_provider),
) -> SetupDetectionSnapshot:
    """Thin orchestration (#39): Market Data -> Features -> Structure ->
    Support/Resistance -> Setup Detection -> Response. No detection logic
    lives here -- this delegates to app.ai_analysis.market_snapshot
    .build_market_snapshot, the same canonical point-in-time pipeline
    app.ai_analysis.evidence_packet uses for a historical `as_of` (Phase
    11.1 #B): "live" is simply that pipeline called with `as_of=now()`,
    never a second implementation of the four engines below."""
    from app.ai_analysis.market_snapshot import build_market_snapshot

    validated_symbol = _validated_symbol(symbol)
    validated_timeframe = _validated_timeframe(timeframe)
    as_of = datetime.now(timezone.utc)

    snapshot = build_market_snapshot(validated_symbol, validated_timeframe, provider, as_of, now=as_of)
    return snapshot.setup_snapshot
