"""Phase 15 §7/§8/§9/§73: independence/episode grouping for
ProspectiveObservations -- overlapping events collapse into one episode
or get purged; genuinely independent events do not."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.market_data import Timeframe
from app.validation.independence import episode_level_sample, purged_sample, sample_counts
from app.validation.schemas import DatasetOrigin, ProspectiveObservation

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _observation(
    obs_id: str, minutes_offset: int, decision_plan_id: str = "plan-1", symbol: str = "SPY"
) -> ProspectiveObservation:
    return ProspectiveObservation(
        observation_id=obs_id,
        alert_id=obs_id,
        decision_plan_id=decision_plan_id,
        symbol=symbol,
        setup_type="breakout_retest",
        direction="bullish",
        timeframe="5m",
        event_type="entry_conditions_met",
        alert_occurred_at=_START + timedelta(minutes=minutes_offset),
        origin=DatasetOrigin.PROSPECTIVE,
        pipeline_version="test",
        resolved=True,
    )


def test_observations_from_the_same_decision_plan_collapse_to_one_episode():
    observations = [
        _observation("o1", 0, decision_plan_id="plan-1"),
        _observation("o2", 5, decision_plan_id="plan-1"),
        _observation("o3", 10, decision_plan_id="plan-1"),
    ]
    episodes = episode_level_sample(observations)
    assert len(episodes) == 1
    # Representative is the earliest by alert_occurred_at.
    assert episodes[0].observation_id == "o1"


def test_observations_from_different_decision_plans_are_separate_episodes():
    observations = [
        _observation("o1", 0, decision_plan_id="plan-1"),
        _observation("o2", 0, decision_plan_id="plan-2"),
    ]
    episodes = episode_level_sample(observations)
    assert len(episodes) == 2


def test_purged_sample_excludes_overlapping_same_symbol_observations():
    # 5m timeframe, horizon_bars=5 -> a 25-minute exclusion window after
    # the selected observation.
    observations = [
        _observation("o1", 0),
        _observation("o2", 10),  # inside o1's 25-minute window -> purged
        _observation("o3", 40),  # outside o1's window -> kept
    ]
    purged = purged_sample(observations, horizon_bars=5, timeframe=Timeframe.FIVE_MIN)
    ids = {o.observation_id for o in purged}
    assert ids == {"o1", "o3"}


def test_purged_sample_does_not_purge_across_different_symbols():
    observations = [
        _observation("o1", 0, symbol="SPY"),
        _observation("o2", 5, symbol="QQQ"),
    ]
    purged = purged_sample(observations, horizon_bars=5, timeframe=Timeframe.FIVE_MIN)
    assert len(purged) == 2


def test_sample_counts_reports_all_three():
    observations = [
        _observation("o1", 0, decision_plan_id="plan-1"),
        _observation("o2", 5, decision_plan_id="plan-1"),
        _observation("o3", 100, decision_plan_id="plan-2"),
    ]
    raw_n, independent_n, purged_n = sample_counts(observations, horizon_bars=5, timeframe=Timeframe.FIVE_MIN)
    assert raw_n == 3
    assert independent_n == 2  # 2 distinct decision plans
    assert purged_n == 2  # o2 purged (overlaps o1's window), o3 independent in time
