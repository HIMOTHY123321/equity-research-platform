"""Shared fixtures for the ai_analysis suite. Same real-candle-fixture +
in-memory-SQLite pattern as tests/integration/test_research_catalysts_routes
.py, factored out so both unit and integration Phase 11 tests build packets
against genuinely realistic (not synthetic) market structure/setups.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.market_data.provider import MarketDataProvider
from app.news.repository import SqlAlchemyNewsRepository
from app.research.repository import SqlAlchemyResearchRepository
from app.schemas.market_data import Timeframe
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


class FakeMarketDataProvider(MarketDataProvider):
    _BY_SYMBOL_TIMEFRAME = {
        ("SPY", Timeframe.ONE_HOUR): SPY_1H,
        ("SPY", Timeframe.ONE_DAY): SPY_1D,
        ("SPY", Timeframe.FOUR_HOUR): SPY_1H,
    }

    def get_candles(self, symbol, timeframe, limit=200):
        candles = self._BY_SYMBOL_TIMEFRAME.get((symbol, timeframe), [])
        return candles[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def make_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    return sessionmaker(bind=engine)()


def make_repositories(session: Session) -> tuple[SqlAlchemyResearchRepository, SqlAlchemyNewsRepository]:
    return SqlAlchemyResearchRepository(session), SqlAlchemyNewsRepository(session)
