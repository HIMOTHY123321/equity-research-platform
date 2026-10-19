"""Long-Term Research orchestration (app.long_term_research.service) --
the proofs that depend on real persistence + transition detection:
unchanged state produces no duplicate push, a transition into a push-
worthy state produces exactly one push, a Pushover failure cannot
corrupt the persisted research state, and the daily scan is
deterministic for identical provider data."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database.models import Symbol, UserPushPreferenceRecord, Watchlist, WatchlistSymbol
from app.long_term_research.fundamentals import FixtureFundamentalsProvider
from app.long_term_research.repository import SqlAlchemyLongTermResearchRepository
from app.long_term_research.schemas import LongTermResearchState
from app.long_term_research.service import run_scan
from app.market_data.provider import MarketDataProvider
from app.notifications.secret_crypto import encrypt_secret
from tests.unit.long_term_research.helpers import (
    strong_positive_candles,
    strong_positive_fundamentals,
    weak_negative_candles,
    weak_negative_fundamentals,
)

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ENCRYPTION_KEY = "test-pushover-key-encryption-key-at-least-32-chars"


def _settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        environment="test",
        push_notifications_enabled=True,
        pushover_app_token="test-app-token",
        pushover_key_encryption_key=_ENCRYPTION_KEY,
    )
    base.update(overrides)
    return Settings(**base)


def make_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    return sessionmaker(bind=engine)()


class FakeMarketDataProvider(MarketDataProvider):
    def __init__(self, candles_by_symbol: dict[str, list]):
        self._candles = candles_by_symbol

    def get_candles(self, symbol, timeframe, limit=200, before=None):
        candles = self._candles.get(symbol, [])
        if before is not None:
            candles = [c for c in candles if c.timestamp < before]
        return candles[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


class _FakePushProviderFactory:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, app_token, user_key):
        self.calls.append((app_token, user_key))

        class _Provider:
            def send(self, message):
                from app.notifications.pushover import PushoverSendResult

                return PushoverSendResult(success=True)

            def close(self):
                pass

        return _Provider()


class _RaisingPushProviderFactory:
    def __call__(self, app_token, user_key):
        raise RuntimeError("Pushover is down")


def _add_watchlist_user(session, symbol: str, *, long_term_push_enabled=False, pushover_key=None):
    user_id = uuid4()
    existing_symbol = session.execute(Symbol.__table__.select().where(Symbol.ticker == symbol)).first()
    if existing_symbol is None:
        session.execute(insert(Symbol).values(ticker=symbol))
        session.commit()
    symbol_row = session.execute(Symbol.__table__.select().where(Symbol.ticker == symbol)).first()

    session.execute(insert(Watchlist).values(user_id=user_id, name="My Watchlist", is_default=True))
    session.commit()
    watchlist_row = session.execute(Watchlist.__table__.select().where(Watchlist.user_id == user_id)).first()
    session.execute(insert(WatchlistSymbol).values(watchlist_id=watchlist_row.id, symbol_id=symbol_row.id))

    encrypted = encrypt_secret(pushover_key, encryption_key=_ENCRYPTION_KEY) if pushover_key else None
    session.execute(
        insert(UserPushPreferenceRecord).values(
            user_id=user_id,
            long_term_push_enabled=long_term_push_enabled,
            pushover_user_key_encrypted=encrypted,
        )
    )
    session.commit()
    return user_id


def test_unchanged_state_does_not_create_a_duplicate_push():
    session = make_session()
    repository = SqlAlchemyLongTermResearchRepository(session)
    user_id = _add_watchlist_user(session, "AAPL", long_term_push_enabled=True, pushover_key="k")
    market_data = FakeMarketDataProvider({"AAPL": strong_positive_candles(AS_OF)})
    fundamentals = FixtureFundamentalsProvider({"AAPL": strong_positive_fundamentals(AS_OF)})
    factory = _FakePushProviderFactory()

    results_day_1 = run_scan(
        ["AAPL"],
        as_of=AS_OF,
        repository=repository,
        market_data_provider=market_data,
        fundamentals_provider=fundamentals,
        settings=_settings(),
        push_provider_factory=factory,
    )
    assert results_day_1[0].research_state == LongTermResearchState.ACCUMULATION_CANDIDATE
    assert len(factory.calls) == 1  # first-ever snapshot into a push-worthy state: exactly one push

    # Day 2: identical data -> identical state -> no second push.
    run_scan(
        ["AAPL"],
        as_of=AS_OF.replace(day=2),
        repository=repository,
        market_data_provider=market_data,
        fundamentals_provider=fundamentals,
        settings=_settings(),
        push_provider_factory=factory,
    )
    assert len(factory.calls) == 1  # still exactly one -- no duplicate
    assert user_id  # keep linter happy about the unused-looking variable


def test_transition_to_accumulation_candidate_creates_exactly_one_push():
    session = make_session()
    repository = SqlAlchemyLongTermResearchRepository(session)
    _add_watchlist_user(session, "AAPL", long_term_push_enabled=True, pushover_key="k")
    market_data = FakeMarketDataProvider({"AAPL": weak_negative_candles(AS_OF)})
    fundamentals = FixtureFundamentalsProvider({"AAPL": weak_negative_fundamentals(AS_OF)})
    factory = _FakePushProviderFactory()

    # Day 1: starts in a non-push-worthy-transition state is not
    # guaranteed here (weak data may itself be push-worthy, e.g.
    # THESIS_INVALIDATED) -- what matters for this test is the DAY-2
    # transition, so we only assert on the delta between day 1 and day 2.
    run_scan(
        ["AAPL"],
        as_of=AS_OF,
        repository=repository,
        market_data_provider=market_data,
        fundamentals_provider=fundamentals,
        settings=_settings(),
        push_provider_factory=factory,
    )
    calls_after_day_1 = len(factory.calls)

    day_2 = AS_OF.replace(day=2)
    market_data_day_2 = FakeMarketDataProvider({"AAPL": strong_positive_candles(day_2)})
    fundamentals_day_2 = FixtureFundamentalsProvider({"AAPL": strong_positive_fundamentals(day_2)})
    results_day_2 = run_scan(
        ["AAPL"],
        as_of=AS_OF.replace(day=2),
        repository=repository,
        market_data_provider=market_data_day_2,
        fundamentals_provider=fundamentals_day_2,
        settings=_settings(),
        push_provider_factory=factory,
    )

    assert results_day_2[0].research_state == LongTermResearchState.ACCUMULATION_CANDIDATE
    assert len(factory.calls) == calls_after_day_1 + 1  # exactly one new push for this transition


def test_transition_to_review_position_creates_exactly_one_push():
    session = make_session()
    repository = SqlAlchemyLongTermResearchRepository(session)
    _add_watchlist_user(session, "AAPL", long_term_push_enabled=True, pushover_key="k")
    market_data_day_1 = FakeMarketDataProvider({"AAPL": strong_positive_candles(AS_OF)})
    fundamentals_day_1 = FixtureFundamentalsProvider({"AAPL": strong_positive_fundamentals(AS_OF)})
    factory = _FakePushProviderFactory()

    results_day_1 = run_scan(
        ["AAPL"],
        as_of=AS_OF,
        repository=repository,
        market_data_provider=market_data_day_1,
        fundamentals_provider=fundamentals_day_1,
        settings=_settings(),
        push_provider_factory=factory,
    )
    assert results_day_1[0].research_state == LongTermResearchState.ACCUMULATION_CANDIDATE
    calls_after_day_1 = len(factory.calls)

    # Day 2: fundamentals/price deteriorate moderately (not the deep
    # trend+fundamentals combination that triggers THESIS_INVALIDATED).
    from app.long_term_research.schemas import FundamentalsSnapshot

    moderately_negative = FundamentalsSnapshot(
        symbol="AAPL",
        fetched_at=AS_OF,
        provider="fixture",
        trailing_pe=40.0,
        profit_margin=-0.02,
        return_on_equity=-0.05,
        debt_to_equity=220.0,
        quarterly_revenue=[195, 177, 161, 146, 133],
        quarterly_eps=[1.95, 1.77, 1.61, 1.46, 1.33],
    )
    market_data_day_2 = FakeMarketDataProvider({"AAPL": strong_positive_candles(AS_OF.replace(day=2))})
    fundamentals_day_2 = FixtureFundamentalsProvider({"AAPL": moderately_negative})
    results_day_2 = run_scan(
        ["AAPL"],
        as_of=AS_OF.replace(day=2),
        repository=repository,
        market_data_provider=market_data_day_2,
        fundamentals_provider=fundamentals_day_2,
        settings=_settings(),
        push_provider_factory=factory,
    )

    assert results_day_2[0].research_state == LongTermResearchState.REVIEW_POSITION
    assert len(factory.calls) == calls_after_day_1 + 1


def test_pushover_failure_cannot_corrupt_the_persisted_research_state():
    session = make_session()
    repository = SqlAlchemyLongTermResearchRepository(session)
    _add_watchlist_user(session, "AAPL", long_term_push_enabled=True, pushover_key="k")
    market_data = FakeMarketDataProvider({"AAPL": strong_positive_candles(AS_OF)})
    fundamentals = FixtureFundamentalsProvider({"AAPL": strong_positive_fundamentals(AS_OF)})

    results = run_scan(
        ["AAPL"],
        as_of=AS_OF,
        repository=repository,
        market_data_provider=market_data,
        fundamentals_provider=fundamentals,
        settings=_settings(),
        push_provider_factory=_RaisingPushProviderFactory(),
    )

    assert results[0].research_state == LongTermResearchState.ACCUMULATION_CANDIDATE
    persisted = repository.get_latest_snapshot("AAPL")
    assert persisted is not None
    assert persisted.research_state == LongTermResearchState.ACCUMULATION_CANDIDATE


def test_daily_scan_is_deterministic_for_identical_provider_data():
    session_a = make_session()
    session_b = make_session()
    repo_a = SqlAlchemyLongTermResearchRepository(session_a)
    repo_b = SqlAlchemyLongTermResearchRepository(session_b)
    candles = strong_positive_candles(AS_OF)
    fundamentals_snapshot = strong_positive_fundamentals(AS_OF)

    results_a = run_scan(
        ["AAPL"],
        as_of=AS_OF,
        repository=repo_a,
        market_data_provider=FakeMarketDataProvider({"AAPL": candles}),
        fundamentals_provider=FixtureFundamentalsProvider({"AAPL": fundamentals_snapshot}),
        settings=_settings(),
    )
    results_b = run_scan(
        ["AAPL"],
        as_of=AS_OF,
        repository=repo_b,
        market_data_provider=FakeMarketDataProvider({"AAPL": candles}),
        fundamentals_provider=FixtureFundamentalsProvider({"AAPL": fundamentals_snapshot}),
        settings=_settings(),
    )

    assert results_a[0].research_state == results_b[0].research_state
    assert results_a[0].factors == results_b[0].factors
    assert results_a[0].reason == results_b[0].reason


def test_snapshot_never_reflects_candles_after_as_of():
    """End-to-end anti-lookahead: candles the market-data provider would
    return for dates AFTER as_of (e.g. a stub that doesn't itself bound
    results) must never change the computed snapshot."""
    session = make_session()
    repository = SqlAlchemyLongTermResearchRepository(session)
    candles = strong_positive_candles(AS_OF)
    fundamentals_snapshot = strong_positive_fundamentals(AS_OF)

    class _UnboundedProvider(MarketDataProvider):
        def get_candles(self, symbol, timeframe, limit=200, before=None):
            # Deliberately ignores `before` -- the WORST case, to prove
            # app.long_term_research.factors' own defensive filtering
            # (not provider cooperation) is what keeps this safe.
            return candles[-limit:]

        def get_latest_quote(self, symbol):
            raise NotImplementedError

        def get_previous_close(self, symbol):
            raise NotImplementedError

    from datetime import timedelta

    future_candles = list(candles)
    for i in range(1, 10):
        future_candle = candles[-1].model_copy(
            update={"timestamp": AS_OF + timedelta(days=i), "close": 99999.0}
        )
        future_candles.append(future_candle)

    class _UnboundedProviderWithFuture(_UnboundedProvider):
        def get_candles(self, symbol, timeframe, limit=200, before=None):
            return future_candles[-limit:]

    baseline = run_scan(
        ["AAPL"],
        as_of=AS_OF,
        repository=repository,
        market_data_provider=_UnboundedProvider(),
        fundamentals_provider=FixtureFundamentalsProvider({"AAPL": fundamentals_snapshot}),
        settings=_settings(),
    )

    session2 = make_session()
    repository2 = SqlAlchemyLongTermResearchRepository(session2)
    with_future = run_scan(
        ["AAPL"],
        as_of=AS_OF,
        repository=repository2,
        market_data_provider=_UnboundedProviderWithFuture(),
        fundamentals_provider=FixtureFundamentalsProvider({"AAPL": fundamentals_snapshot}),
        settings=_settings(),
    )

    assert baseline[0].price == with_future[0].price
    assert baseline[0].research_state == with_future[0].research_state
    assert baseline[0].factors == with_future[0].factors
