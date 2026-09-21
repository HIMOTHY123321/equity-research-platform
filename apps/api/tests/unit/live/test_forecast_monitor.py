"""Phase 12.1 (#I/#K): ForecastMonitor -- background, page-independent
forecast resolution. Every test here calls `scan_and_resolve_once()`
directly with no FastAPI app, no HTTP request, and no browser page at all,
which is itself the proof that resolution genuinely does not depend on any
page being open (#K "resolves with page closed").
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.forecasting.repository import SqlAlchemyForecastRepository
from app.forecasting.schemas import ForecastCategory, ForecastStatus
from app.forecasting.service import create_forecast
from app.live.forecast_monitor import ForecastMonitor
from app.news.fixture_provider import FixtureNewsProvider
from app.news.repository import SqlAlchemyNewsRepository
from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.engine import execute_research_run
from app.research.repository import SqlAlchemyResearchRepository
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1D, SPY_1H, FakeMarketDataProvider
from tests.unit.forecasting.conftest import CREATION_AS_OF, some_candidate_id


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    return sessionmaker(bind=engine)


def _seed(factory) -> tuple:
    session = factory()
    research_repository = SqlAlchemyResearchRepository(session)
    news_repository = SqlAlchemyNewsRepository(session)
    evidence_repository = SqlAlchemyEvidenceRepository(session)
    forecast_repository = SqlAlchemyForecastRepository(session)
    execute_research_run(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        start_date=SPY_1H[0].timestamp,
        end_date=CREATION_AS_OF,
        primary_candles=SPY_1H,
        daily_candles=SPY_1D,
        four_hour_candles=SPY_1H,
        provider_name="fixture",
        repository=research_repository,
        research_config=DEFAULT_RESEARCH_CONFIG,
    )
    return research_repository, news_repository, evidence_repository, forecast_repository


def _create_structure_forecast(
    research_repository, news_repository, evidence_repository, forecast_repository
):
    candidate_id = some_candidate_id()
    return create_forecast(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        forecast_category=ForecastCategory.STRUCTURE,
        horizon_bars=100,
        setup_id=candidate_id,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        evidence_repository=evidence_repository,
        forecast_repository=forecast_repository,
        market_as_of=CREATION_AS_OF,
    )


def test_scan_resolves_a_forecast_whose_horizon_has_already_closed():
    factory = _session_factory()
    research_repository, news_repository, evidence_repository, forecast_repository = _seed(factory)
    forecast = _create_structure_forecast(
        research_repository, news_repository, evidence_repository, forecast_repository
    )
    assert forecast.status == ForecastStatus.ACTIVE

    monitor = ForecastMonitor(session_factory=factory, market_provider=FakeMarketDataProvider())
    events = monitor.scan_and_resolve_once()

    assert len(events) == 1
    assert events[0].forecast_id == forecast.forecast_id
    persisted = forecast_repository.get_outcome_for_forecast(forecast.forecast_id)
    assert persisted is not None
    assert persisted.outcome.value in ("correct", "incorrect")


def test_scan_skips_a_forecast_that_already_has_an_outcome():
    factory = _session_factory()
    research_repository, news_repository, evidence_repository, forecast_repository = _seed(factory)
    _create_structure_forecast(
        research_repository, news_repository, evidence_repository, forecast_repository
    )

    monitor = ForecastMonitor(session_factory=factory, market_provider=FakeMarketDataProvider())
    first_events = monitor.scan_and_resolve_once()
    assert len(first_events) == 1

    second_events = monitor.scan_and_resolve_once()
    assert second_events == []  # already resolved -- not re-processed


def test_insufficient_future_data_is_never_persisted_and_remains_rescannable():
    factory = _session_factory()
    research_repository, news_repository, evidence_repository, forecast_repository = _seed(factory)
    # An enormous horizon can never resolve against the fixture's finite history.
    candidate_id = some_candidate_id()
    forecast = create_forecast(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        forecast_category=ForecastCategory.STRUCTURE,
        horizon_bars=100_000,
        setup_id=candidate_id,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        evidence_repository=evidence_repository,
        forecast_repository=forecast_repository,
        market_as_of=CREATION_AS_OF,
    )

    monitor = ForecastMonitor(session_factory=factory, market_provider=FakeMarketDataProvider())
    first = monitor.scan_and_resolve_once()
    assert first == []  # insufficient -- nothing resolved, nothing persisted
    assert forecast_repository.get_outcome_for_forecast(forecast.forecast_id) is None

    # A second scan tries again rather than being permanently blocked.
    second = monitor.scan_and_resolve_once()
    assert second == []
    assert forecast_repository.get_outcome_for_forecast(forecast.forecast_id) is None


def test_listener_receives_the_resolved_event():
    factory = _session_factory()
    research_repository, news_repository, evidence_repository, forecast_repository = _seed(factory)
    forecast = _create_structure_forecast(
        research_repository, news_repository, evidence_repository, forecast_repository
    )

    monitor = ForecastMonitor(session_factory=factory, market_provider=FakeMarketDataProvider())
    queue = monitor.add_listener()
    monitor.scan_and_resolve_once()

    event = queue.get_nowait()
    assert event.forecast_id == forecast.forecast_id
    assert event.symbol == "SPY"


def test_original_forecast_is_never_mutated_by_background_resolution():
    factory = _session_factory()
    research_repository, news_repository, evidence_repository, forecast_repository = _seed(factory)
    forecast = _create_structure_forecast(
        research_repository, news_repository, evidence_repository, forecast_repository
    )
    snapshot = forecast.model_dump()

    monitor = ForecastMonitor(session_factory=factory, market_provider=FakeMarketDataProvider())
    monitor.scan_and_resolve_once()

    reloaded = forecast_repository.get_forecast(forecast.forecast_id)
    assert reloaded.model_dump() == snapshot
