from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Symbol, Watchlist, WatchlistSymbol
from app.long_term_research.repository import SqlAlchemyLongTermResearchRepository
from app.long_term_research.schemas import (
    BusinessQualityState,
    EarningsTrendState,
    GrowthState,
    LongTermEvidenceQuality,
    LongTermFactorBundle,
    LongTermFactorEvidence,
    LongTermResearchResult,
    LongTermResearchState,
    LongTermTrendState,
    ValuationState,
)

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    return sessionmaker(bind=engine)()


def _factors() -> LongTermFactorBundle:
    empty = LongTermFactorEvidence()
    return LongTermFactorBundle(
        business_quality=BusinessQualityState.STRONG,
        business_quality_evidence=empty,
        earnings_trend=EarningsTrendState.IMPROVING,
        earnings_trend_evidence=empty,
        valuation=ValuationState.CHEAP,
        valuation_evidence=empty,
        growth=GrowthState.STRONG,
        growth_evidence=empty,
        long_term_trend=LongTermTrendState.CONSTRUCTIVE,
        long_term_trend_evidence=empty,
        history_days=500,
        limited_history=False,
    )


def _result(symbol: str, state: LongTermResearchState, *, as_of: datetime = AS_OF) -> LongTermResearchResult:
    return LongTermResearchResult(
        symbol=symbol,
        as_of=as_of,
        price=100.0,
        research_state=state,
        factors=_factors(),
        evidence_quality=LongTermEvidenceQuality.STRONG,
        positive_evidence=["positive"],
        negative_evidence=[],
        contradictions=[],
        missing_evidence=[],
        reason="reason",
        what_would_change_state="change",
        market_data_provider="fixture",
        fundamentals_provider="fixture",
    )


def _add_to_watchlist(session, user_id, ticker: str) -> None:
    symbol = session.execute(Symbol.__table__.select().where(Symbol.ticker == ticker)).first()
    if symbol is None:
        session.execute(insert(Symbol).values(ticker=ticker))
        session.commit()
    symbol_row = session.execute(Symbol.__table__.select().where(Symbol.ticker == ticker)).first()

    watchlist_row = session.execute(
        Watchlist.__table__.select().where(Watchlist.user_id == user_id)
    ).first()
    if watchlist_row is None:
        session.execute(insert(Watchlist).values(user_id=user_id, name="My Watchlist", is_default=True))
        session.commit()
        watchlist_row = session.execute(
            Watchlist.__table__.select().where(Watchlist.user_id == user_id)
        ).first()

    session.execute(insert(WatchlistSymbol).values(watchlist_id=watchlist_row.id, symbol_id=symbol_row.id))
    session.commit()


def test_insert_and_get_latest_snapshot():
    repo = SqlAlchemyLongTermResearchRepository(make_session())
    repo.insert_snapshot(_result("AAPL", LongTermResearchState.ACCUMULATION_CANDIDATE))

    latest = repo.get_latest_snapshot("AAPL")
    assert latest is not None
    assert latest.research_state == LongTermResearchState.ACCUMULATION_CANDIDATE
    assert latest.positive_evidence == ["positive"]


def test_get_latest_snapshot_returns_none_for_unknown_symbol():
    repo = SqlAlchemyLongTermResearchRepository(make_session())
    assert repo.get_latest_snapshot("ZZZZ") is None


def test_latest_snapshot_is_the_most_recent_by_as_of_not_insertion_order():
    repo = SqlAlchemyLongTermResearchRepository(make_session())
    older = AS_OF
    newer = AS_OF.replace(day=2)
    repo.insert_snapshot(_result("AAPL", LongTermResearchState.HOLDING_THESIS_INTACT, as_of=newer))
    repo.insert_snapshot(_result("AAPL", LongTermResearchState.ACCUMULATION_CANDIDATE, as_of=older))

    latest = repo.get_latest_snapshot("AAPL")
    assert latest.research_state == LongTermResearchState.HOLDING_THESIS_INTACT


def test_snapshots_are_never_updated_in_place_both_rows_persist():
    session = make_session()
    repo = SqlAlchemyLongTermResearchRepository(session)
    repo.insert_snapshot(_result("AAPL", LongTermResearchState.ACCUMULATION_CANDIDATE, as_of=AS_OF))
    repo.insert_snapshot(
        _result("AAPL", LongTermResearchState.REVIEW_POSITION, as_of=AS_OF.replace(day=2))
    )

    from app.database.models import LongTermResearchSnapshotRecord

    count = session.query(LongTermResearchSnapshotRecord).filter_by(symbol="AAPL").count()
    assert count == 2


def test_list_latest_snapshots_only_returns_requested_symbols_that_exist():
    repo = SqlAlchemyLongTermResearchRepository(make_session())
    repo.insert_snapshot(_result("AAPL", LongTermResearchState.ACCUMULATION_CANDIDATE))

    latest = repo.list_latest_snapshots(["AAPL", "MSFT"])
    assert set(latest.keys()) == {"AAPL"}


def test_user_watchlist_symbols_are_scoped_to_that_user_only():
    session = make_session()
    repo = SqlAlchemyLongTermResearchRepository(session)
    user_a, user_b = uuid4(), uuid4()
    _add_to_watchlist(session, user_a, "AAPL")
    _add_to_watchlist(session, user_b, "MSFT")

    assert repo.list_user_watchlist_symbols(user_a) == ["AAPL"]
    assert repo.list_user_watchlist_symbols(user_b) == ["MSFT"]


def test_all_watchlist_symbols_union_deduplicates_across_users():
    session = make_session()
    repo = SqlAlchemyLongTermResearchRepository(session)
    user_a, user_b = uuid4(), uuid4()
    _add_to_watchlist(session, user_a, "AAPL")
    _add_to_watchlist(session, user_b, "AAPL")
    _add_to_watchlist(session, user_b, "MSFT")

    assert repo.list_all_watchlist_symbols_union() == ["AAPL", "MSFT"]


def test_push_eligible_user_ids_requires_watchlist_membership_enabled_and_key():
    session = make_session()
    repo = SqlAlchemyLongTermResearchRepository(session)
    eligible_user, no_watchlist_user, disabled_user, no_key_user = (uuid4(), uuid4(), uuid4(), uuid4())

    for user_id in (eligible_user, disabled_user, no_key_user):
        _add_to_watchlist(session, user_id, "AAPL")
    _add_to_watchlist(session, no_watchlist_user, "MSFT")

    repo.set_long_term_push_enabled(eligible_user, True)
    repo.set_long_term_push_enabled(disabled_user, False)
    repo.set_long_term_push_enabled(no_key_user, True)

    from app.database.models import UserPushPreferenceRecord

    session.execute(
        UserPushPreferenceRecord.__table__.update()
        .where(UserPushPreferenceRecord.user_id == eligible_user)
        .values(pushover_user_key_encrypted="encrypted-key")
    )
    session.commit()

    assert repo.list_push_eligible_user_ids("AAPL") == [eligible_user]


def test_long_term_push_enabled_defaults_to_false_and_can_be_toggled():
    repo = SqlAlchemyLongTermResearchRepository(make_session())
    user_id = uuid4()
    assert repo.get_long_term_push_enabled(user_id) is False

    repo.set_long_term_push_enabled(user_id, True)
    assert repo.get_long_term_push_enabled(user_id) is True

    repo.set_long_term_push_enabled(user_id, False)
    assert repo.get_long_term_push_enabled(user_id) is False


def test_claim_scheduled_scan_run_is_idempotent_per_day():
    repo = SqlAlchemyLongTermResearchRepository(make_session())
    first = repo.claim_scheduled_scan_run(run_date="2026-01-01", as_of=AS_OF, symbol_count=5)
    second = repo.claim_scheduled_scan_run(run_date="2026-01-01", as_of=AS_OF, symbol_count=5)
    third_different_day = repo.claim_scheduled_scan_run(
        run_date="2026-01-02", as_of=AS_OF.replace(day=2), symbol_count=5
    )

    assert first is True
    assert second is False
    assert third_different_day is True
