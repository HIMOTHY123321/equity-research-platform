"""Persistence tests (#L, #M). File-backed SQLite inside a
TemporaryDirectory, not in-memory-only -- reopen-after-close is actually
exercised. Every session/engine created against a tempdir path is closed
and disposed in try/finally BEFORE the TemporaryDirectory context exits,
same fix applied to app.research's persistence tests earlier this session --
Windows keeps a file-backed SQLite connection's OS handle open until
disposed, and TemporaryDirectory cleanup cannot delete an still-open file.
"""

from __future__ import annotations

import os
import tempfile

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.news.fixture_provider import FixtureNewsProvider
from app.news.repository import SqlAlchemyNewsRepository
from tests.unit.news.conftest import et, raw_article


def _session_for(db_path):
    engine = create_engine(f"sqlite:///{db_path}")
    return sessionmaker(bind=engine)()


def _articles(raw):
    far_future = et(2030, 1, 1)
    return FixtureNewsProvider(raw).fetch_market_news(et(2000, 1, 1), far_future, far_future)


def test_upsert_articles_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        session = _session_for(db_path)
        try:
            repository = SqlAlchemyNewsRepository(session)
            articles = _articles(
                [raw_article("Acme reports quarterly earnings", et(2026, 8, 20, 9, 0), ["ACME"])]
            )
            first = repository.upsert_articles(articles)
            second = repository.upsert_articles(articles)
            assert first == 1
            assert second == 0
        finally:
            session.close()
            session.get_bind().dispose()


def test_no_duplicate_article_created_on_re_ingestion_across_reopen():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        articles = _articles(
            [raw_article("Acme reports quarterly earnings", et(2026, 8, 20, 9, 0), ["ACME"])]
        )

        session_a = _session_for(db_path)
        try:
            SqlAlchemyNewsRepository(session_a).upsert_articles(articles)
        finally:
            session_a.close()
            session_a.get_bind().dispose()

        session_b = _session_for(db_path)
        try:
            repository_b = SqlAlchemyNewsRepository(session_b)
            inserted_again = repository_b.upsert_articles(articles)
            all_for_symbol = repository_b.get_articles_for_symbol(
                "ACME", et(2000, 1, 1), et(2030, 1, 1), et(2030, 1, 1)
            )
            assert inserted_again == 0
            assert len(all_for_symbol) == 1
        finally:
            session_b.close()
            session_b.get_bind().dispose()


def test_events_snapshot_persistence_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        session = _session_for(db_path)
        try:
            repository = SqlAlchemyNewsRepository(session)
            articles = _articles(
                [
                    raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"]),
                    raw_article("Acme Q2 earnings per share top estimates", et(2026, 8, 20, 9, 5), ["ACME"]),
                ]
            )
            repository.upsert_articles(articles)
            events = repository.events_for_symbol_as_of(
                "ACME", et(2000, 1, 1), et(2030, 1, 1), et(2030, 1, 1)
            )

            repository.persist_events_snapshot(events)
            repository.persist_events_snapshot(events)  # must not duplicate

            recent = repository.list_recent_events()
            assert len(recent) == 1
            assert recent[0].event_id == events[0].event_id
        finally:
            session.close()
            session.get_bind().dispose()


def test_reaction_upsert_is_idempotent_and_never_overwrites():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        session = _session_for(db_path)
        try:
            from app.news.reaction import measure_market_reaction
            from app.news.schemas import CatalystCategory, CatalystEvent
            from tests.unit.setup_detection.conftest import load_real_candles

            candles = load_real_candles("SPY_1h")
            event = CatalystEvent(
                event_id="evt-1",
                primary_timestamp=candles[100].timestamp,
                category=CatalystCategory.EARNINGS,
                affected_symbols=("SPY",),
                contributing_article_ids=["a1"],
                source_count=1,
                earliest_published_at=candles[100].timestamp,
                latest_update_at=candles[100].timestamp,
                title="test",
            )
            repository = SqlAlchemyNewsRepository(session)
            reaction = measure_market_reaction(event, "SPY", "1h", candles)
            repository.upsert_reaction(reaction)
            repository.upsert_reaction(reaction)  # no-op, must not raise (unique constraint respected)

            fetched = repository.get_reaction("evt-1", "SPY", "1h")
            assert fetched is not None
            assert fetched.base_price == reaction.base_price
        finally:
            session.close()
            session.get_bind().dispose()


def test_get_reaction_returns_none_when_absent():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        session = _session_for(db_path)
        try:
            repository = SqlAlchemyNewsRepository(session)
            assert repository.get_reaction("nope", "SPY", "1h") is None
        finally:
            session.close()
            session.get_bind().dispose()


def test_get_event_by_id_and_articles_by_ids():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        session = _session_for(db_path)
        try:
            repository = SqlAlchemyNewsRepository(session)
            articles = _articles(
                [raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"])]
            )
            repository.upsert_articles(articles)
            events = repository.events_for_symbol_as_of(
                "ACME", et(2000, 1, 1), et(2030, 1, 1), et(2030, 1, 1)
            )
            repository.persist_events_snapshot(events)

            fetched_event = repository.get_event_by_id(events[0].event_id)
            assert fetched_event is not None
            fetched_articles = repository.get_articles_by_ids(fetched_event.contributing_article_ids)
            assert len(fetched_articles) == 1

            assert repository.get_event_by_id("does-not-exist") is None
            assert repository.get_articles_by_ids([]) == []
        finally:
            session.close()
            session.get_bind().dispose()
