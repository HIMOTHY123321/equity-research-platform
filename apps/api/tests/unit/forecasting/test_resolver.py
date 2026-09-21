"""Phase 12 (#G): app.forecasting.resolver is the *only* place future data
may enter this package -- these tests prove that boundary directly: a
ForwardForecast is never mutated by resolution, an unresolvable horizon
abstains as INSUFFICIENT_FUTURE_DATA rather than guessing, and horizons are
counted in real bars (not calendar time), so weekend/holiday gaps in the
underlying candle series are handled for free.
"""

from __future__ import annotations

from app.ai_analysis.evidence_packet import build_evidence_packet
from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.forecasting.resolver import resolve_forecast
from app.forecasting.schemas import (
    EvidenceQualityState,
    ForecastCategory,
    ForecastOrigin,
    ForecastOutcomeCategory,
    ForecastStatus,
    ForwardForecast,
    StructureForecastValue,
)
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1H, FakeMarketDataProvider, make_session
from tests.unit.forecasting.conftest import CREATION_AS_OF, seeded_repositories, some_candidate_id

_CREATION_INDEX = next(i for i, c in enumerate(SPY_1H) if c.timestamp == CREATION_AS_OF)
_BASE_CLOSE = SPY_1H[_CREATION_INDEX].close


def _direction_forecast(horizon_bars: int, forecast_value: str, packet_id: str) -> ForwardForecast:
    return ForwardForecast(
        forecast_id=f"direction-h{horizon_bars}-{forecast_value}",
        created_at=CREATION_AS_OF,
        market_as_of=CREATION_AS_OF,
        symbol="SPY",
        timeframe="1h",
        forecast_category=ForecastCategory.DIRECTION,
        forecast_value=forecast_value,
        forecast_horizon_bars=horizon_bars,
        evidence_packet_id=packet_id,
        evidence_packet_schema_version="1.0",
        pipeline_version="1.0",
        evidence_quality=EvidenceQualityState.MIXED_EVIDENCE,
        origin=ForecastOrigin.DETERMINISTIC_RESEARCH,
        status=ForecastStatus.ACTIVE,
    )


def test_resolving_a_known_down_move_is_correct_for_a_down_forecast():
    # h=100 from the creation anchor is a genuine ~-1.57% move in the real
    # SPY_1H fixture (probed directly against the fixture data).
    forecast = _direction_forecast(100, "down", "packet-x")
    outcome = resolve_forecast(forecast, FakeMarketDataProvider(), evidence_repository=None)
    assert outcome.outcome == ForecastOutcomeCategory.CORRECT
    assert outcome.actual_value == "down"
    assert outcome.actual_forward_return_percent < 0


def test_resolving_a_known_down_move_is_incorrect_for_an_up_forecast():
    forecast = _direction_forecast(100, "up", "packet-x")
    outcome = resolve_forecast(forecast, FakeMarketDataProvider(), evidence_repository=None)
    assert outcome.outcome == ForecastOutcomeCategory.INCORRECT


def test_horizon_exactly_at_the_edge_of_available_future_data_resolves():
    # Exactly 124 future candles exist past the creation anchor.
    forecast = _direction_forecast(124, "down", "packet-x")
    outcome = resolve_forecast(forecast, FakeMarketDataProvider(), evidence_repository=None)
    assert outcome.outcome != ForecastOutcomeCategory.INSUFFICIENT_FUTURE_DATA


def test_horizon_one_bar_beyond_available_future_data_is_insufficient():
    forecast = _direction_forecast(125, "down", "packet-x")
    outcome = resolve_forecast(forecast, FakeMarketDataProvider(), evidence_repository=None)
    assert outcome.outcome == ForecastOutcomeCategory.INSUFFICIENT_FUTURE_DATA
    assert outcome.actual_value is None


def test_resolution_never_mutates_the_original_forecast():
    forecast = _direction_forecast(50, "up", "packet-x")
    snapshot = forecast.model_dump()
    resolve_forecast(forecast, FakeMarketDataProvider(), evidence_repository=None)
    assert forecast.model_dump() == snapshot


def test_outcome_is_a_separate_record_linked_by_forecast_id():
    forecast = _direction_forecast(10, "up", "packet-x")
    outcome = resolve_forecast(forecast, FakeMarketDataProvider(), evidence_repository=None)
    assert outcome.forecast_id == forecast.forecast_id
    assert outcome.outcome_id != forecast.forecast_id


def test_resolution_as_of_is_strictly_after_market_as_of():
    forecast = _direction_forecast(5, "up", "packet-x")
    outcome = resolve_forecast(forecast, FakeMarketDataProvider(), evidence_repository=None)
    assert outcome.resolution_as_of > forecast.market_as_of


def test_abstained_forecast_resolves_to_insufficient_future_data():
    forecast = ForwardForecast(
        forecast_id="abstained-1",
        created_at=CREATION_AS_OF,
        market_as_of=CREATION_AS_OF,
        symbol="SPY",
        timeframe="1h",
        forecast_category=ForecastCategory.DIRECTION,
        forecast_value=None,
        forecast_horizon_bars=5,
        evidence_packet_id="packet-x",
        evidence_packet_schema_version="1.0",
        pipeline_version="1.0",
        evidence_quality=EvidenceQualityState.INSUFFICIENT_EVIDENCE,
        origin=ForecastOrigin.DETERMINISTIC_RESEARCH,
        status=ForecastStatus.ABSTAINED,
        abstention_reason="stale_data",
    )
    outcome = resolve_forecast(forecast, FakeMarketDataProvider(), evidence_repository=None)
    assert outcome.outcome == ForecastOutcomeCategory.INSUFFICIENT_FUTURE_DATA


def test_structure_forecast_resolves_against_real_future_structure():
    # Regression guard: support/resistance zone IDs are a pure function of
    # cluster membership (app.support_resistance.ids.zone_id) and shift as
    # soon as one more candle arrives and levels re-cluster -- an exact
    # zone_ref match against a snapshot rebuilt even one bar later almost
    # always misses. The resolver re-identifies "the same structural level"
    # by price-range overlap against the *original* packet's zone bounds
    # instead of requiring the exact ID to still exist.
    #
    # This test isolates that resolver behavior from generate_structure_
    # forecast's own evidence-quality gate (#J) -- the fixture's real
    # research quality for this candidate is WEAK_EVIDENCE, which correctly
    # abstains at creation time (covered by test_deterministic.py); the
    # forecast here is constructed directly, exactly like
    # _direction_forecast above, to test zone re-identification on its own.
    session = make_session()
    research_repository, news_repository = seeded_repositories()
    evidence_repository = SqlAlchemyEvidenceRepository(session)

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
        forecast_id="structure-real-fixture",
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

    outcome = resolve_forecast(forecast, FakeMarketDataProvider(), evidence_repository)
    assert outcome.outcome in (ForecastOutcomeCategory.CORRECT, ForecastOutcomeCategory.INCORRECT)
    assert outcome.actual_value is not None
