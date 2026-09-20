"""Phase 12 (#A/#F): ForwardForecast/ForecastOutcome structural invariants --
immutability, closed-set validation, and the abstained/non-abstained shape
rules. These are schema-level guarantees the rest of the package leans on,
so they're tested directly against the Pydantic models with no pipeline
involved.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.forecasting.schemas import (
    AbstentionReason,
    DirectionForecastValue,
    EvidenceQualityState,
    ForecastCategory,
    ForecastOrigin,
    ForecastStatus,
    ForwardForecast,
)

_NOW = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)


def _base_kwargs(**overrides) -> dict:
    kwargs = dict(
        forecast_id="a" * 40,
        created_at=_NOW,
        market_as_of=_NOW,
        symbol="SPY",
        timeframe="1h",
        forecast_category=ForecastCategory.DIRECTION,
        forecast_value=DirectionForecastValue.UP.value,
        forecast_horizon_bars=5,
        evidence_packet_id="b" * 40,
        evidence_packet_schema_version="1.0",
        pipeline_version="1.0",
        evidence_quality=EvidenceQualityState.MIXED_EVIDENCE,
        origin=ForecastOrigin.DETERMINISTIC_RESEARCH,
        status=ForecastStatus.ACTIVE,
    )
    kwargs.update(overrides)
    return kwargs


def test_forecast_cannot_be_edited_after_creation():
    forecast = ForwardForecast(**_base_kwargs())
    with pytest.raises(ValidationError):
        forecast.forecast_value = DirectionForecastValue.DOWN.value


def test_forecast_value_must_be_a_member_of_the_closed_set_for_its_category():
    with pytest.raises(ValidationError):
        ForwardForecast(**_base_kwargs(forecast_value="strong_buy"))


def test_ai_cannot_invent_a_probability_flavored_value():
    with pytest.raises(ValidationError):
        ForwardForecast(**_base_kwargs(forecast_value="72% chance up"))


def test_forecast_value_from_a_different_category_is_rejected():
    # "volatility_expands" is a real enum value -- just not for DIRECTION.
    with pytest.raises(ValidationError):
        ForwardForecast(
            **_base_kwargs(forecast_category=ForecastCategory.DIRECTION, forecast_value="volatility_expands")
        )


def test_abstained_forecast_must_have_no_forecast_value():
    with pytest.raises(ValidationError):
        ForwardForecast(
            **_base_kwargs(
                status=ForecastStatus.ABSTAINED,
                abstention_reason=AbstentionReason.TOO_FEW_PURGED_EPISODES,
                forecast_value=DirectionForecastValue.UP.value,
            )
        )


def test_abstained_forecast_must_carry_a_reason():
    with pytest.raises(ValidationError):
        ForwardForecast(**_base_kwargs(status=ForecastStatus.ABSTAINED, forecast_value=None))


def test_abstained_forecast_with_a_reason_and_no_value_is_valid():
    forecast = ForwardForecast(
        **_base_kwargs(
            status=ForecastStatus.ABSTAINED,
            forecast_value=None,
            abstention_reason=AbstentionReason.HIGH_OVERLAP,
        )
    )
    assert forecast.status == ForecastStatus.ABSTAINED
    assert forecast.forecast_value is None


def test_non_abstained_forecast_requires_a_forecast_value():
    with pytest.raises(ValidationError):
        ForwardForecast(**_base_kwargs(status=ForecastStatus.ACTIVE, forecast_value=None))


def test_created_at_retains_second_precision():
    stamp = datetime(2026, 6, 15, 14, 30, 47, tzinfo=timezone.utc)
    forecast = ForwardForecast(**_base_kwargs(created_at=stamp, market_as_of=stamp))
    assert forecast.created_at.second == 47
    assert forecast.created_at.tzinfo is not None
