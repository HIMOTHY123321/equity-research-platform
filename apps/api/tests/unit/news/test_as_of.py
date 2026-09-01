"""Anti-lookahead tests (#E) -- the non-negotiable section. Every claim here
is about what a caller querying "as of" some historical instant T can see,
and specifically that ingesting/appending articles published AFTER T can
never change what a query at T returns.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.market_structure.schemas import Direction
from app.news.events import group_into_events
from app.news.fixture_provider import FixtureNewsProvider
from app.news.repository import SqlAlchemyNewsRepository
from app.news.schemas import CatalystCategory
from app.news.setup_linking import build_setup_catalyst_context
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupCandidate, SetupLifecycleState
from tests.unit.news.conftest import et, raw_article


def _in_memory_repository() -> SqlAlchemyNewsRepository:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    session = sessionmaker(bind=engine)()
    return SqlAlchemyNewsRepository(session)


def test_future_article_not_visible_at_old_as_of():
    raw = [raw_article("Acme reports quarterly earnings", et(2026, 8, 20, 9, 0), ["ACME"])]
    provider = FixtureNewsProvider(raw)
    old_as_of = et(2026, 8, 19)
    result = provider.fetch_symbol_news("ACME", et(2026, 1, 1), et(2026, 12, 31), old_as_of)
    assert result == []


def test_article_visible_once_as_of_passes_its_publication():
    raw = [raw_article("Acme reports quarterly earnings", et(2026, 8, 20, 9, 0), ["ACME"])]
    provider = FixtureNewsProvider(raw)
    result = provider.fetch_symbol_news("ACME", et(2026, 1, 1), et(2026, 12, 31), et(2026, 8, 20, 9, 0))
    assert len(result) == 1


def test_appending_future_article_does_not_change_grouping_at_a_fixed_as_of():
    as_of = et(2026, 8, 20, 12, 0)
    base_raw = [
        raw_article(
            "Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"], source="Reuters"
        ),
        raw_article(
            "Acme Q2 earnings per share top estimates", et(2026, 8, 20, 9, 5), ["ACME"], source="Bloomberg"
        ),
    ]
    future_raw = base_raw + [
        raw_article("Acme unveils new product launch", et(2026, 8, 25, 9, 0), ["ACME"], source="CNBC"),
    ]

    articles_at_as_of_before = FixtureNewsProvider(base_raw).fetch_symbol_news(
        "ACME", et(2026, 1, 1), et(2026, 12, 31), as_of
    )
    articles_at_as_of_after = FixtureNewsProvider(future_raw).fetch_symbol_news(
        "ACME", et(2026, 1, 1), et(2026, 12, 31), as_of
    )

    events_before = group_into_events(articles_at_as_of_before)
    events_after = group_into_events(articles_at_as_of_after)

    assert [e.event_id for e in events_before] == [e.event_id for e in events_after]


def test_repository_as_of_query_is_unaffected_by_a_later_ingested_article():
    repository = _in_memory_repository()
    as_of = et(2026, 8, 20, 12, 0)

    early = FixtureNewsProvider(
        [raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"])]
    ).fetch_symbol_news("ACME", et(2026, 1, 1), et(2026, 12, 31), as_of)
    repository.upsert_articles(early)

    events_before = repository.events_for_symbol_as_of("ACME", et(2026, 1, 1), et(2026, 12, 31), as_of)

    # Ingest a genuinely future article (published after `as_of`).
    future = FixtureNewsProvider(
        [raw_article("Acme unveils new product launch", et(2026, 8, 25, 9, 0), ["ACME"])]
    ).fetch_symbol_news("ACME", et(2026, 1, 1), et(2026, 12, 31), et(2026, 12, 31))
    repository.upsert_articles(future)

    events_after = repository.events_for_symbol_as_of("ACME", et(2026, 1, 1), et(2026, 12, 31), as_of)

    assert [e.event_id for e in events_before] == [e.event_id for e in events_after]
    assert len(events_before) == 1


def test_events_for_symbol_as_of_excludes_articles_published_after_as_of():
    repository = _in_memory_repository()
    provider = FixtureNewsProvider(
        [
            raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"]),
            raw_article("Acme unveils new product launch", et(2026, 8, 25, 9, 0), ["ACME"]),
        ]
    )
    all_articles = provider.fetch_symbol_news("ACME", et(2026, 1, 1), et(2026, 12, 31), et(2026, 12, 31))
    repository.upsert_articles(all_articles)

    as_of = et(2026, 8, 21)
    events = repository.events_for_symbol_as_of("ACME", et(2026, 1, 1), et(2026, 12, 31), as_of)
    assert len(events) == 1
    assert events[0].category == CatalystCategory.EARNINGS


def _candidate(symbol, timestamp, direction=Direction.BULLISH):
    return SetupCandidate(
        id=f"{symbol}-{timestamp.isoformat()}",
        symbol=symbol,
        timeframe=Timeframe.ONE_HOUR,
        setup_type="breakout_retest",
        direction=direction,
        candidate_candle_timestamp=timestamp,
        created_at=timestamp,
        current_state=SetupLifecycleState.QUALIFIED,
        transitions=[],
        hard_checks=[],
        soft_checks=[],
        conflicts=[],
    )


def test_setup_catalyst_context_only_ever_sees_events_the_caller_supplied():
    """build_setup_catalyst_context performs no fetching itself -- passing
    it a caller-filtered event list is the entire anti-lookahead guarantee
    at this layer; an event NOT in the list can never appear in the result,
    even if it would otherwise be the temporally nearest one."""
    detection_time = et(2026, 8, 20, 12, 0)
    candidate = _candidate("ACME", detection_time)

    included = FixtureNewsProvider(
        [raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 10, 0), ["ACME"])]
    ).fetch_market_news(et(2026, 1, 1), et(2026, 12, 31), et(2026, 12, 31))
    excluded = FixtureNewsProvider(
        [raw_article("Acme unveils new product launch", et(2026, 8, 20, 11, 30), ["ACME"])]
    ).fetch_market_news(et(2026, 1, 1), et(2026, 12, 31), et(2026, 12, 31))

    included_events = group_into_events(included)
    excluded_events = group_into_events(excluded)
    assert len(included_events) == 1
    assert len(excluded_events) == 1

    context = build_setup_catalyst_context(candidate, included_events, {})
    assert context.nearest_catalyst is not None
    assert context.nearest_catalyst.event_id == included_events[0].event_id
    assert context.nearest_catalyst.event_id != excluded_events[0].event_id
