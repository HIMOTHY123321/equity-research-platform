"""Phase 12 (#F/#P): SqlAlchemyForecastRepository -- `save_forecast`/
`save_outcome`/`save_gate_version` are idempotent on their business key,
which is the mechanical enforcement behind "a forecast cannot be edited."
There is deliberately no `update_forecast` anywhere to test the absence of.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.forecasting.repository import SqlAlchemyForecastRepository
from app.forecasting.schemas import (
    EvidenceQualityState,
    ForecastCategory,
    ForecastOrigin,
    ForecastOutcome,
    ForecastOutcomeCategory,
    ForecastStatus,
    ForwardForecast,
)
from tests.unit.ai_analysis.conftest import make_session

_NOW = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)


def _forecast(forecast_id="f-1", value="up"):
    return ForwardForecast(
        forecast_id=forecast_id,
        created_at=_NOW,
        market_as_of=_NOW,
        symbol="SPY",
        timeframe="1h",
        forecast_category=ForecastCategory.DIRECTION,
        forecast_value=value,
        forecast_horizon_bars=5,
        evidence_packet_id="packet-1",
        evidence_packet_schema_version="1.0",
        pipeline_version="1.0",
        evidence_quality=EvidenceQualityState.MIXED_EVIDENCE,
        origin=ForecastOrigin.DETERMINISTIC_RESEARCH,
        status=ForecastStatus.ACTIVE,
    )


def _outcome(forecast_id="f-1", actual="up"):
    return ForecastOutcome(
        outcome_id=f"outcome-{forecast_id}-{actual}",
        forecast_id=forecast_id,
        resolved_at=_NOW,
        resolution_as_of=_NOW,
        outcome=ForecastOutcomeCategory.CORRECT,
        actual_value=actual,
    )


def _repo() -> SqlAlchemyForecastRepository:
    return SqlAlchemyForecastRepository(make_session())


def test_save_forecast_round_trips():
    repo = _repo()
    forecast = _forecast()
    repo.save_forecast(forecast)
    fetched = repo.get_forecast(forecast.forecast_id)
    assert fetched == forecast


def test_saving_the_same_forecast_id_twice_is_a_no_op_not_an_overwrite():
    repo = _repo()
    first = _forecast(value="up")
    attempted_edit = _forecast(value="down")  # same forecast_id, different value
    repo.save_forecast(first)
    repo.save_forecast(attempted_edit)
    fetched = repo.get_forecast("f-1")
    assert fetched.forecast_value == "up"  # the original, never overwritten


def test_repository_exposes_no_update_method():
    assert not hasattr(SqlAlchemyForecastRepository, "update_forecast")


def test_save_outcome_round_trips_and_links_by_forecast_id():
    repo = _repo()
    repo.save_forecast(_forecast())
    outcome = _outcome()
    repo.save_outcome(outcome)
    fetched = repo.get_outcome_for_forecast("f-1")
    assert fetched == outcome


def test_a_forecast_can_only_ever_have_one_outcome():
    repo = _repo()
    repo.save_forecast(_forecast())
    repo.save_outcome(_outcome(actual="up"))
    repo.save_outcome(_outcome(actual="down"))  # a second, contradictory resolution attempt
    fetched = repo.get_outcome_for_forecast("f-1")
    assert fetched.actual_value == "up"  # the first resolution wins, never silently replaced


def test_list_forecasts_filters_by_symbol_and_status():
    repo = _repo()
    repo.save_forecast(_forecast(forecast_id="f-spy"))
    other = _forecast(forecast_id="f-other")
    other = other.model_copy(update={"symbol": "AAPL"})
    repo.save_forecast(other)
    results = repo.list_forecasts(symbol="SPY")
    assert {f.forecast_id for f in results} == {"f-spy"}


def test_gate_version_is_idempotent():
    repo = _repo()
    repo.save_gate_version("v1", {"min_prospective_forecast_count": 30})
    repo.save_gate_version("v1", {"min_prospective_forecast_count": 999})  # attempted silent goalpost move
    assert repo.get_gate_version("v1")["min_prospective_forecast_count"] == 30


def test_gate_result_history_accumulates_rather_than_overwrites():
    repo = _repo()
    repo.save_gate_version("v1", {})
    repo.save_gate_result("v1", _NOW, "fail", {"accuracy": 0.4})
    later = _NOW.replace(hour=15)
    repo.save_gate_result("v1", later, "pass", {"accuracy": 0.6})
    latest = repo.get_latest_gate_result("v1")
    assert latest["accuracy"] == 0.6
