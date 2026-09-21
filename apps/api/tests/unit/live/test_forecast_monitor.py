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

from app.ai_analysis.evidence_packet import build_evidence_packet
from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.forecasting.repository import SqlAlchemyForecastRepository
from app.forecasting.schemas import (
    EvidenceQualityState,
    ForecastCategory,
    ForecastOrigin,
    ForecastStatus,
    ForwardForecast,
    StructureForecastValue,
)
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
    """Builds a real packet from the fixture pipeline, then constructs the
    ForwardForecast directly (ACTIVE) rather than via `create_forecast`'s
    own deterministic generator -- the fixture's real research quality for
    this candidate is WEAK_EVIDENCE, which `generate_structure_forecast`
    now correctly abstains on (#J). These tests exist to exercise
    ForecastMonitor's scan/resolve mechanics, not evidence-quality gating
    at creation time (that's covered by tests/unit/forecasting/
    test_deterministic.py), so an ACTIVE forecast is constructed directly,
    same pattern as tests/unit/forecasting/test_resolver.py's structure
    test."""
    candidate_id = some_candidate_id()
    packet = build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        setup_id=candidate_id,
        as_of=CREATION_AS_OF,
    )
    evidence_repository.save_packet(packet)
    assert packet.setup is not None
    bullish = packet.setup.candidate.direction.value == "bullish"
    sr = packet.support_resistance
    zone = sr.nearest_resistance if bullish else sr.nearest_support
    assert zone is not None, "fixture candidate must have a real zone on its own side to test against"

    forecast = ForwardForecast(
        forecast_id=f"structure-monitor-{candidate_id}",
        created_at=CREATION_AS_OF,
        market_as_of=CREATION_AS_OF,
        symbol="SPY",
        timeframe="1h",
        forecast_category=ForecastCategory.STRUCTURE,
        forecast_value=(
            StructureForecastValue.RESISTANCE_BREAKS.value
            if bullish
            else StructureForecastValue.SUPPORT_FAILS.value
        ),
        forecast_horizon_bars=100,
        zone_ref=zone.id,
        evidence_packet_id=packet.packet_id,
        evidence_packet_schema_version=packet.schema_version,
        pipeline_version=packet.pipeline_version,
        evidence_quality=EvidenceQualityState.MIXED_EVIDENCE,
        origin=ForecastOrigin.DETERMINISTIC_RESEARCH,
        status=ForecastStatus.ACTIVE,
    )
    forecast_repository.save_forecast(forecast)
    return forecast


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
