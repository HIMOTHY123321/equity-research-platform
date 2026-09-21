"""Phase 12.1 regression guard: repository constructors each lazily call
`Base.metadata.create_all(..., checkfirst=True)` -- safe under a single
request at a time, but this phase adds several always-on background
threads (RecomputationEngine/ForecastMonitor/NewsMonitor, each doing DB
work via asyncio.to_thread) that now routinely start at the same moment as
a browser's first request. On a brand-new database, checkfirst's own
"inspect, then create if missing" is not atomic across separate
connections -- two threads can both see a table as missing and both issue
CREATE TABLE, and the loser raises "table already exists"
(sqlite3.OperationalError), observed live during this phase's browser
validation.

app.main.lifespan's fix: create every table once, synchronously, before
any background thread starts. This test proves the mechanism directly --
after that eager creation, concurrent repository construction from many
threads (simulating the real race) never raises.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Base
from app.news.repository import SqlAlchemyNewsRepository


def test_concurrent_repository_construction_after_eager_schema_creation_never_races():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # The fix under test: create every table once, up front, exactly as
    # app.main.lifespan now does before starting any background thread.
    Base.metadata.create_all(bind=engine, checkfirst=True)

    session_factory = sessionmaker(bind=engine)
    errors: list[Exception] = []

    def _construct_repository() -> None:
        try:
            SqlAlchemyNewsRepository(session_factory())
        except Exception as exc:  # noqa: BLE001 -- capturing for the assertion below
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: _construct_repository(), range(50)))

    assert errors == []
