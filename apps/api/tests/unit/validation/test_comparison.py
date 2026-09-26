"""Phase 15 §23: historical vs prospective comparison -- the two datasets
are never combined into one estimate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.validation.comparison import compare_historical_vs_prospective
from app.validation.schemas import DatasetOrigin, ProspectiveObservation

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _observation(obs_id: str, return_5: float) -> ProspectiveObservation:
    return ProspectiveObservation(
        observation_id=obs_id,
        alert_id=obs_id,
        symbol="SPY",
        setup_type="breakout_retest",
        direction="bullish",
        timeframe="1h",
        event_type="entry_conditions_met",
        alert_occurred_at=_START + timedelta(hours=1),
        origin=DatasetOrigin.PROSPECTIVE,
        pipeline_version="test",
        resolved=True,
        return_5=return_5,
    )


def test_no_data_on_either_side_is_disclosed_not_hidden():
    comparison = compare_historical_vs_prospective("cohort", [], [], horizon_bars=5)
    assert comparison.historical_n == 0
    assert comparison.prospective_n == 0
    assert comparison.note is not None


def test_agreeing_directions_are_flagged_as_agreement():
    observations = [_observation(f"o{i}", 1.0) for i in range(3)]
    comparison = compare_historical_vs_prospective(
        "cohort", [0.8, 0.9, 1.0], observations, horizon_bars=5
    )
    assert comparison.direction_agreement is True


def test_opposite_directions_are_flagged_as_disagreement():
    observations = [_observation(f"o{i}", -1.0) for i in range(3)]
    comparison = compare_historical_vs_prospective(
        "cohort", [0.8, 0.9, 1.0], observations, horizon_bars=5
    )
    assert comparison.direction_agreement is False


def test_datasets_are_never_merged_into_a_single_estimate():
    observations = [_observation(f"o{i}", 5.0) for i in range(3)]
    comparison = compare_historical_vs_prospective(
        "cohort", [1.0, 1.0, 1.0], observations, horizon_bars=5
    )
    # Both medians remain independently visible -- never averaged together.
    assert comparison.historical_median_effect == 1.0
    assert comparison.prospective_median_effect == 5.0
