"""Local candle cache and frozen datasets (Phase 9 #32-#34). Two distinct
concerns, deliberately not conflated:

- **Cache** (`get`/`put`): a pure performance accelerator, keyed on the
  full `(provider, symbol, timeframe, requested_start, requested_end,
  adjustment_mode, session_settings)` tuple -- never a partial or
  per-symbol-only key, so a request for a different range is always a
  genuine cache miss rather than a silent substitution. "Never silently
  stale" is enforced by `_is_cacheable`: a request whose `requested_end`
  falls within `REVISION_WINDOW_DAYS` of "now" always bypasses the cache
  entirely, on both read and write -- yfinance (and most providers) can
  still revise recent bars after the fact (docs/decisions/0006), so
  caching them at all would risk serving data the provider itself would no
  longer return. Only ranges old enough to be considered settled are ever
  cached.
- **Frozen datasets** (`freeze`/`get_frozen`): an explicit, separate,
  permanently-immutable snapshot for exact reproducibility, keyed only by
  its own generated id -- never by the request tuple, so it can never be
  silently overwritten or invalidated by a later fetch of the "same"
  range, and (unlike the cache) freezing is allowed regardless of
  recency: the whole point is capturing exactly what the provider returned
  at one specific moment.

Same ABC + SqlAlchemy-impl + local-SQLite-bootstrap convention as
`app.research.repository` and `app.research_intelligence.snapshots`.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Base, CachedCandleSeriesRecord, FrozenDatasetRecord
from app.market_data.provider import MarketDataProvider
from app.research.provenance import compute_candle_data_hash
from app.schemas.market_data import Candle, Timeframe

# Hardcoded to match the one value every call site already assumes
# (app.research.provenance, app.research_intelligence.manifest) -- not
# read from the provider, since neither current provider exposes these as
# a real per-call parameter yet (see docs/decisions/0006).
DEFAULT_ADJUSTMENT_MODE = "unadjusted"
DEFAULT_SESSION_SETTINGS = "regular_and_extended (prepost=True)"

# Recent data within this many days of "now" is never cached or served
# from cache -- see module docstring.
REVISION_WINDOW_DAYS = 5


def _is_cacheable(requested_end: datetime, now: datetime) -> bool:
    end = requested_end if requested_end.tzinfo is not None else requested_end.replace(tzinfo=timezone.utc)
    return (now - end) >= timedelta(days=REVISION_WINDOW_DAYS)


class CandleCacheRepository(ABC):
    @abstractmethod
    def get(
        self,
        *,
        provider: str,
        symbol: str,
        timeframe: str,
        requested_start: datetime,
        requested_end: datetime,
        adjustment_mode: str,
        session_settings: str,
    ) -> Optional[list[Candle]]: ...

    @abstractmethod
    def put(
        self,
        *,
        provider: str,
        symbol: str,
        timeframe: str,
        requested_start: datetime,
        requested_end: datetime,
        adjustment_mode: str,
        session_settings: str,
        candles: list[Candle],
    ) -> None: ...

    @abstractmethod
    def freeze(
        self,
        *,
        label: str,
        provider: str,
        symbol: str,
        timeframe: str,
        requested_start: datetime,
        requested_end: datetime,
        adjustment_mode: str,
        session_settings: str,
        candles: list[Candle],
    ) -> str: ...

    @abstractmethod
    def get_frozen(self, freeze_id: str) -> Optional[list[Candle]]: ...

    @abstractmethod
    def list_frozen_datasets(self, *, limit: int = 50) -> list[dict]: ...


class SqlAlchemyCandleCacheRepository(CandleCacheRepository):
    def __init__(self, session: Session, now: Optional[datetime] = None) -> None:
        self._session = session
        # Injectable for tests -- never `datetime.now()` called ad hoc
        # inside the cacheability check itself, so the revision-window
        # boundary is exactly reproducible in tests.
        self._now = now or datetime.now(timezone.utc)
        Base.metadata.create_all(
            bind=session.get_bind(),
            tables=[CachedCandleSeriesRecord.__table__, FrozenDatasetRecord.__table__],
            checkfirst=True,
        )

    def get(
        self,
        *,
        provider,
        symbol,
        timeframe,
        requested_start,
        requested_end,
        adjustment_mode,
        session_settings,
    ) -> Optional[list[Candle]]:
        if not _is_cacheable(requested_end, self._now):
            return None
        row = self._session.execute(
            select(CachedCandleSeriesRecord).where(
                CachedCandleSeriesRecord.provider == provider,
                CachedCandleSeriesRecord.symbol == symbol,
                CachedCandleSeriesRecord.timeframe == timeframe,
                CachedCandleSeriesRecord.requested_start == requested_start,
                CachedCandleSeriesRecord.requested_end == requested_end,
                CachedCandleSeriesRecord.adjustment_mode == adjustment_mode,
                CachedCandleSeriesRecord.session_settings == session_settings,
            )
        ).scalar_one_or_none()
        return [Candle(**c) for c in row.candles] if row is not None else None

    def put(
        self,
        *,
        provider,
        symbol,
        timeframe,
        requested_start,
        requested_end,
        adjustment_mode,
        session_settings,
        candles,
    ) -> None:
        if not _is_cacheable(requested_end, self._now):
            return  # never write data that's still inside the revision window
        existing = self._session.execute(
            select(CachedCandleSeriesRecord).where(
                CachedCandleSeriesRecord.provider == provider,
                CachedCandleSeriesRecord.symbol == symbol,
                CachedCandleSeriesRecord.timeframe == timeframe,
                CachedCandleSeriesRecord.requested_start == requested_start,
                CachedCandleSeriesRecord.requested_end == requested_end,
                CachedCandleSeriesRecord.adjustment_mode == adjustment_mode,
                CachedCandleSeriesRecord.session_settings == session_settings,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return  # a settled-range entry is never overwritten once cached
        row = CachedCandleSeriesRecord(
            provider=provider,
            symbol=symbol,
            timeframe=timeframe,
            requested_start=requested_start,
            requested_end=requested_end,
            adjustment_mode=adjustment_mode,
            session_settings=session_settings,
            candles=[c.model_dump(mode="json") for c in candles],
            data_hash=compute_candle_data_hash(candles),
        )
        self._session.add(row)
        self._session.commit()

    def freeze(
        self,
        *,
        label,
        provider,
        symbol,
        timeframe,
        requested_start,
        requested_end,
        adjustment_mode,
        session_settings,
        candles,
    ) -> str:
        row = FrozenDatasetRecord(
            label=label,
            provider=provider,
            symbol=symbol,
            timeframe=timeframe,
            requested_start=requested_start,
            requested_end=requested_end,
            adjustment_mode=adjustment_mode,
            session_settings=session_settings,
            candles=[c.model_dump(mode="json") for c in candles],
            data_hash=compute_candle_data_hash(candles),
        )
        self._session.add(row)
        self._session.commit()
        return str(row.id)

    def get_frozen(self, freeze_id: str) -> Optional[list[Candle]]:
        try:
            row = self._session.get(FrozenDatasetRecord, uuid.UUID(freeze_id))
        except ValueError:
            return None
        return [Candle(**c) for c in row.candles] if row is not None else None

    def list_frozen_datasets(self, *, limit: int = 50) -> list[dict]:
        rows = self._session.execute(
            select(FrozenDatasetRecord).order_by(FrozenDatasetRecord.created_at.desc()).limit(limit)
        ).scalars()
        return [
            {
                "freeze_id": str(r.id),
                "label": r.label,
                "provider": r.provider,
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "requested_start": r.requested_start,
                "requested_end": r.requested_end,
                "candle_count": len(r.candles),
                "data_hash": r.data_hash,
                "created_at": r.created_at,
            }
            for r in rows
        ]


def fetch_candles_cached(
    provider: MarketDataProvider,
    cache: CandleCacheRepository,
    provider_name: str,
    symbol: str,
    timeframe: Timeframe,
    requested_start: datetime,
    requested_end: datetime,
    limit: int,
    adjustment_mode: str = DEFAULT_ADJUSTMENT_MODE,
    session_settings: str = DEFAULT_SESSION_SETTINGS,
) -> list[Candle]:
    """The one place a replay route should get candles from now on: a
    cache-or-fetch wrapper around `provider.get_candles`, transparent to
    the caller -- same return shape either way. `requested_start`/
    `requested_end` are the caller's intended replay range (not
    necessarily identical to the earliest/latest candle actually
    returned), matching the same "intent vs. actual" distinction
    `DatasetProvenance` already draws.
    """
    cached = cache.get(
        provider=provider_name,
        symbol=symbol,
        timeframe=timeframe.value,
        requested_start=requested_start,
        requested_end=requested_end,
        adjustment_mode=adjustment_mode,
        session_settings=session_settings,
    )
    if cached is not None:
        return cached

    candles = provider.get_candles(symbol, timeframe, limit=limit)
    cache.put(
        provider=provider_name,
        symbol=symbol,
        timeframe=timeframe.value,
        requested_start=requested_start,
        requested_end=requested_end,
        adjustment_mode=adjustment_mode,
        session_settings=session_settings,
        candles=candles,
    )
    return candles
