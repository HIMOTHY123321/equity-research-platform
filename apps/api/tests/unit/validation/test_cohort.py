"""Phase 15 §10/§11/§12/§74: cohort statistics assembly -- known
deterministic fixture, exact expected mean/median/n/effect."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.market_data import Timeframe
from app.validation.cohort import build_cohort_statistics
from app.validation.schemas import BaselineType, DatasetOrigin, ProspectiveObservation

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _observation(
    obs_id: str, day_offset: int, return_5: float, symbol: str = "SPY"
) -> ProspectiveObservation:
    return ProspectiveObservation(
        observation_id=obs_id,
        alert_id=obs_id,
        decision_plan_id=f"plan-{obs_id}",
        symbol=symbol,
        setup_type="breakout_retest",
        direction="bullish",
        timeframe="1h",
        event_type="entry_conditions_met",
        alert_occurred_at=_START + timedelta(days=day_offset),
        origin=DatasetOrigin.PROSPECTIVE,
        pipeline_version="test",
        resolved=True,
        return_5=return_5,
    )


def test_known_fixture_produces_exact_mean_and_median():
    observations = [_observation(f"o{i}", i, float(v)) for i, v in enumerate([1.0, 2.0, 3.0, 4.0, 5.0])]
    stats = build_cohort_statistics("test_cohort", observations, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert stats.raw_n == 5
    assert stats.median == 3.0
    assert stats.mean == 3.0
    assert stats.positive_rate == 1.0


def test_unresolved_observations_with_no_horizon_data_are_excluded_from_statistics():
    observations = [_observation("o1", 0, 1.0)]
    unresolved = observations[0].model_copy(
        update={"resolved": False, "observation_id": "o2", "alert_id": "o2", "return_5": None}
    )
    stats = build_cohort_statistics(
        "test_cohort", observations + [unresolved], horizon_bars=5, timeframe=Timeframe.ONE_HOUR
    )
    assert stats.raw_n == 1  # only the one with an actual return_5 counted


def test_partially_resolved_observation_still_counts_for_its_own_resolved_horizon():
    # Phase 15 per-horizon resolution: an observation whose OTHER horizons
    # are still pending (resolved=False, resolution_quality=PARTIAL) must
    # still count toward THIS horizon's cohort stats if this horizon's own
    # return is already resolved -- never held hostage by an unrelated,
    # still-pending horizon.
    observations = [_observation("o1", 0, 1.0)]
    partially_resolved = observations[0].model_copy(
        update={"resolved": False, "observation_id": "o2", "alert_id": "o2", "return_5": 3.0}
    )
    stats = build_cohort_statistics(
        "test_cohort", observations + [partially_resolved], horizon_bars=5, timeframe=Timeframe.ONE_HOUR
    )
    assert stats.raw_n == 2


def test_baseline_effect_is_cohort_median_minus_baseline_median():
    observations = [_observation(f"o{i}", i, 2.0) for i in range(3)]
    stats = build_cohort_statistics(
        "test_cohort",
        observations,
        horizon_bars=5,
        timeframe=Timeframe.ONE_HOUR,
        baseline_type=BaselineType.UNCONDITIONAL,
        baseline_comparison_returns=[0.5, 0.5, 0.5],
    )
    assert stats.baseline_median == 0.5
    assert stats.effect_vs_baseline == 1.5


def test_empty_cohort_never_fabricates_statistics():
    stats = build_cohort_statistics("empty", [], horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert stats.raw_n == 0
    assert stats.median is None
    assert stats.mean is None
    assert stats.positive_rate is None
    assert stats.bootstrap_available is False
