from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.market_data.sessions import EXCHANGE_TZ
from app.schemas.market_data import Candle, MarketSession, Timeframe


def alpaca_bar(t: str, o: float, h: float, l: float, c: float, v: float) -> dict:  # noqa: E741
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


def et(year, month, day, hour, minute=0, second=0) -> datetime:
    """Build a tz-aware datetime in exchange local time (America/New_York)."""
    return datetime(year, month, day, hour, minute, second, tzinfo=EXCHANGE_TZ)


def utc(year, month, day, hour, minute=0, second=0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def make_candle(
    symbol: str = "AAPL",
    timeframe: Timeframe = Timeframe.ONE_HOUR,
    timestamp: datetime = None,
    session: MarketSession = MarketSession.REGULAR,
    open: float = 100.0,  # noqa: A002
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.5,
    volume: float = 1000.0,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp or utc(2026, 8, 17, 14, 30),
        session=session,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


class FileSessionFactory:
    """Phase 14.1: builds `sessionmaker`s bound to real on-disk (not
    `:memory:`) temp-file SQLite databases -- needed by any test that
    exercises genuine multi-connection concurrent access or simulates a
    process restart against the same file. Every Engine created via
    __call__ is tracked so dispose_all() can close every pooled
    connection/file handle at teardown.

    Root cause this fixes: SQLAlchemy's internal compiled-statement
    caching keeps a live reference to any Engine that has executed a
    cached-shape query, so plain Python GC never reclaims an un-disposed
    Engine -- its connection pool (and the open OS file handle to its
    now-abandoned temp directory) stays alive for the rest of the pytest
    process. Across the full suite this accumulates across every
    file-based-engine test, which is why isolated per-file runs were fast
    but the full combined run took hours instead of minutes."""

    def __init__(self, filename: str = "test.db") -> None:
        self._filename = filename
        self.engines: list[Engine] = []

    def new_db_path(self) -> Path:
        return Path(tempfile.mkdtemp()) / self._filename

    def __call__(self, db_path: Optional[Path] = None) -> sessionmaker:
        """One call = one fresh Engine. Pass an explicit db_path (as
        returned by a prior new_db_path()/__call__) to point a brand-new
        Engine at an EXISTING file -- used by restart-simulation tests
        that need a genuinely fresh Engine reconnecting to the same
        on-disk state, exactly like a real process restart."""
        path = db_path if db_path is not None else self.new_db_path()
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        self.engines.append(engine)
        return sessionmaker(bind=engine)

    def dispose_all(self) -> None:
        for engine in self.engines:
            engine.dispose()
        self.engines.clear()


@pytest.fixture
def file_session_factory():
    """Yields a FileSessionFactory; every Engine it creates during the
    test is disposed at teardown, even if the test fails (see
    FileSessionFactory's docstring for why this matters)."""
    factory = FileSessionFactory()
    try:
        yield factory
    finally:
        factory.dispose_all()
