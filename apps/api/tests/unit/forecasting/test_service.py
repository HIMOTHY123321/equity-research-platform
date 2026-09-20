"""Phase 12 (#F/#J): app.forecasting.service.create_forecast -- the only
place a ForwardForecast comes into existence. `market_as_of=None` (the only
form the public API route ever calls) must tag the result PROSPECTIVE;
supplying an explicit `market_as_of` (internal-only, exercised here for
testability against fixture data) tags it BACKTEST_REPLAY, and
app.forecasting.gate already excludes anything not PROSPECTIVE -- so this
is the structural half of "never backfill a prospective forecast."
"""

from __future__ import annotations

from app.ai_analysis.repository import SqlAlchemyEvidenceRepository
from app.forecasting.repository import SqlAlchemyForecastRepository
from app.forecasting.schemas import ForecastCategory, ForecastRunMode
from app.forecasting.service import create_forecast
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import FakeMarketDataProvider, make_session
from tests.unit.forecasting.conftest import CREATION_AS_OF, seeded_repositories, some_candidate_id


def _create(**overrides):
    session = make_session()
    research_repository, news_repository = seeded_repositories()
    evidence_repository = SqlAlchemyEvidenceRepository(session)
    forecast_repository = SqlAlchemyForecastRepository(session)
    kwargs = dict(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        forecast_category=ForecastCategory.STRUCTURE,
        horizon_bars=20,
        setup_id=some_candidate_id(),
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        evidence_repository=evidence_repository,
        forecast_repository=forecast_repository,
        market_as_of=CREATION_AS_OF,
    )
    kwargs.update(overrides)
    return create_forecast(**kwargs), forecast_repository


def test_supplying_market_as_of_tags_backtest_replay_not_prospective():
    forecast, _repo = _create()
    assert forecast.run_mode == ForecastRunMode.BACKTEST_REPLAY


def test_omitting_market_as_of_tags_prospective_and_uses_live_now():
    # Symbol-level (no setup_id) -- a specific historical candidate id
    # would not generally still be present in "live now"'s own detection
    # snapshot, which is not what this test is checking.
    forecast, _repo = _create(
        market_as_of=None, setup_id=None, forecast_category=ForecastCategory.VOLATILITY
    )
    assert forecast.run_mode == ForecastRunMode.PROSPECTIVE


def test_forecast_id_is_deterministic_for_the_same_inputs():
    first, _ = _create()
    second, _ = _create()
    assert first.forecast_id == second.forecast_id


def test_forecast_binds_to_a_real_saved_evidence_packet():
    forecast, repo = _create()
    assert forecast.evidence_packet_id
    saved = repo.get_forecast(forecast.forecast_id)
    assert saved is not None
    assert saved.evidence_packet_id == forecast.evidence_packet_id


def test_a_second_create_call_for_the_same_instant_does_not_duplicate():
    session = make_session()
    research_repository, news_repository = seeded_repositories()
    evidence_repository = SqlAlchemyEvidenceRepository(session)
    forecast_repository = SqlAlchemyForecastRepository(session)
    candidate_id = some_candidate_id()

    def _make():
        return create_forecast(
            symbol="SPY",
            timeframe=Timeframe.ONE_HOUR,
            forecast_category=ForecastCategory.STRUCTURE,
            horizon_bars=20,
            setup_id=candidate_id,
            market_provider=FakeMarketDataProvider(),
            news_provider=FixtureNewsProvider([]),
            news_repository=news_repository,
            research_repository=research_repository,
            evidence_repository=evidence_repository,
            forecast_repository=forecast_repository,
            market_as_of=CREATION_AS_OF,
        )

    first = _make()
    second = _make()
    assert first.forecast_id == second.forecast_id
    assert len(forecast_repository.list_forecasts(symbol="SPY", limit=100)) == 1
