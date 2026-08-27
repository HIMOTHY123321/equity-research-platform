"""Shared helpers for the research test suite. Reuses the same static real
SPY/QQQ/NVDA fixture (#38) `tests/unit/setup_detection/conftest.py` already
loads -- no network access required anywhere in this package.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.features.engine import compute_feature_snapshot
from app.market_structure.engine import compute_market_structure_snapshot
from app.research.repository import SqlAlchemyResearchRepository
from app.schemas.market_data import Timeframe
from app.setup_detection.engine import compute_setup_detection_snapshot
from app.support_resistance.engine import compute_support_resistance_snapshot
from tests.unit.setup_detection.conftest import hour_bar, load_real_candles  # noqa: F401

SYMBOL = "TEST"


def in_memory_repository() -> SqlAlchemyResearchRepository:
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    return SqlAlchemyResearchRepository(session)


def live_snapshot_at(symbol, timeframe, candles, daily_candles, four_hour_candles, as_of):
    """Exactly mirrors one replay.py step -- used to prove replay/live
    parity (#4, #47.1) by construction rather than by coincidence."""
    feature_snapshot = compute_feature_snapshot(symbol, timeframe, candles, daily_candles, as_of)
    structure_by_timeframe = {
        Timeframe.ONE_DAY: compute_market_structure_snapshot(symbol, Timeframe.ONE_DAY, daily_candles, as_of),
        Timeframe.FOUR_HOUR: compute_market_structure_snapshot(
            symbol, Timeframe.FOUR_HOUR, four_hour_candles, as_of
        ),
    }
    if timeframe not in structure_by_timeframe:
        structure_by_timeframe[timeframe] = compute_market_structure_snapshot(
            symbol, timeframe, candles, as_of
        )
    levels_snapshot = compute_support_resistance_snapshot(
        symbol, timeframe, candles, daily_candles, structure_by_timeframe, as_of
    )
    return compute_setup_detection_snapshot(
        symbol,
        timeframe,
        candles,
        daily_candles,
        feature_snapshot,
        structure_by_timeframe,
        levels_snapshot,
        as_of,
    )
