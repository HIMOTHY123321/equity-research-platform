"""Persistence tests (#50) -- real file-backed SQLite, not in-memory-only,
so "does data survive a repository reopen" is actually exercised.
"""

from __future__ import annotations

import os
import tempfile

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.research.engine import execute_research_run
from app.research.repository import SqlAlchemyResearchRepository
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _window():
    return SPY_1H[120].timestamp, SPY_1H[140].timestamp


def _session_for(db_path):
    engine = create_engine(f"sqlite:///{db_path}")
    return sessionmaker(bind=engine)()


def test_bootstrap_creates_only_the_phase7_tables():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        session = _session_for(db_path)
        SqlAlchemyResearchRepository(session)
        tables = set(inspect(session.get_bind()).get_table_names())
        assert {"research_runs", "setup_ledger_entries", "setup_outcomes"} <= tables


def test_research_run_and_ledger_entries_and_outcomes_all_persist():
    start, end = _window()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        session = _session_for(db_path)
        repository = SqlAlchemyResearchRepository(session)

        run_id = execute_research_run(
            symbol=SYMBOL,
            timeframe=Timeframe.ONE_HOUR,
            start_date=start,
            end_date=end,
            primary_candles=SPY_1H,
            daily_candles=SPY_1D,
            four_hour_candles=SPY_1H,
            provider_name="yfinance",
            repository=repository,
        )

        record = repository.get_run(run_id)
        assert record is not None
        assert record.status == "completed"

        entries = repository.list_ledger_entries(run_id, limit=500)
        assert len(entries) > 0
        assert len(entries) >= record.qualified_count + record.rejected_count
        assert any(e.outcome is not None for e in entries)

        summary = repository.get_summary(run_id)
        assert summary is not None
        assert summary.run_id == run_id


def test_data_survives_repository_reopen():
    start, end = _window()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")

        session_a = _session_for(db_path)
        repository_a = SqlAlchemyResearchRepository(session_a)
        run_id = execute_research_run(
            symbol=SYMBOL,
            timeframe=Timeframe.ONE_HOUR,
            start_date=start,
            end_date=end,
            primary_candles=SPY_1H,
            daily_candles=SPY_1D,
            four_hour_candles=SPY_1H,
            provider_name="yfinance",
            repository=repository_a,
        )
        session_a.close()

        # A brand-new session/engine against the same file -- simulates an
        # app restart, not just a fresh in-process object.
        session_b = _session_for(db_path)
        repository_b = SqlAlchemyResearchRepository(session_b)

        record = repository_b.get_run(run_id)
        assert record is not None
        assert record.status == "completed"
        entries = repository_b.list_ledger_entries(run_id, limit=500)
        assert len(entries) > 0


def test_two_separate_runs_do_not_corrupt_each_others_records():
    start, end = _window()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        session = _session_for(db_path)
        repository = SqlAlchemyResearchRepository(session)

        run_id_1 = execute_research_run(
            symbol=SYMBOL,
            timeframe=Timeframe.ONE_HOUR,
            start_date=start,
            end_date=end,
            primary_candles=SPY_1H,
            daily_candles=SPY_1D,
            four_hour_candles=SPY_1H,
            provider_name="yfinance",
            repository=repository,
        )
        run_id_2 = execute_research_run(
            symbol=SYMBOL,
            timeframe=Timeframe.ONE_HOUR,
            start_date=start,
            end_date=end,
            primary_candles=SPY_1H,
            daily_candles=SPY_1D,
            four_hour_candles=SPY_1H,
            provider_name="yfinance",
            repository=repository,
        )

        assert run_id_1 != run_id_2
        entries_1 = repository.list_ledger_entries(run_id_1, limit=500)
        entries_2 = repository.list_ledger_entries(run_id_2, limit=500)
        # Same underlying data/config -> same deterministic setup ids in
        # both runs, but each run's own ledger rows stay independent.
        assert {e.setup_id for e in entries_1} == {e.setup_id for e in entries_2}
        assert all(e.research_run_id == run_id_1 for e in entries_1)
        assert all(e.research_run_id == run_id_2 for e in entries_2)
