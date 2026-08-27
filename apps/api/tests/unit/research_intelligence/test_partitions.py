from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.partitions import build_partition_plan, partition_for_timestamp
from app.research_intelligence.schemas import Partition


def _timestamps(n: int):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(hours=i) for i in range(n)]


def test_hand_calculated_split_for_100_bars_at_60_20_20():
    # 100 bars, ratios 0.6/0.2/0.2 -> 60/20/20 exactly, no rounding ambiguity.
    plan = build_partition_plan("SPY", "1h", _timestamps(100))
    counts = {b.partition: b.bar_count for b in plan.bounds}
    assert counts[Partition.DEVELOPMENT] == 60
    assert counts[Partition.VALIDATION] == 20
    assert counts[Partition.TEST] == 20
    assert sum(counts.values()) == 100


def test_partitions_are_contiguous_and_chronologically_ordered():
    plan = build_partition_plan("SPY", "1h", _timestamps(100))
    for earlier, later in zip(plan.bounds, plan.bounds[1:]):
        assert earlier.end < later.start


def test_no_timestamp_belongs_to_more_than_one_partition():
    timestamps = _timestamps(97)  # deliberately not evenly divisible, to exercise rounding
    plan = build_partition_plan("SPY", "1h", timestamps)
    assignments = [partition_for_timestamp(plan, ts) for ts in timestamps]
    assert all(a is not None for a in assignments)
    # Every bar is assigned, and the total assigned count matches every bar exactly once.
    assert len(assignments) == len(timestamps)
    total_bar_count = sum(b.bar_count for b in plan.bounds)
    assert total_bar_count == len(timestamps)


def test_rounding_remainder_is_absorbed_by_the_test_partition_not_dropped():
    plan = build_partition_plan("SPY", "1h", _timestamps(97))
    assert sum(b.bar_count for b in plan.bounds) == 97


def test_shuffled_timestamps_are_rejected():
    timestamps = _timestamps(10)
    shuffled = [timestamps[1], timestamps[0]] + timestamps[2:]
    with pytest.raises(ValueError, match="chronologically sorted"):
        build_partition_plan("SPY", "1h", shuffled)


def test_empty_series_is_rejected():
    with pytest.raises(ValueError, match="zero bars"):
        build_partition_plan("SPY", "1h", [])


def test_timestamp_outside_the_plans_range_returns_none():
    timestamps = _timestamps(10)
    plan = build_partition_plan("SPY", "1h", timestamps)
    far_future = timestamps[-1] + timedelta(days=365)
    assert partition_for_timestamp(plan, far_future) is None


def test_custom_ratios_are_respected():
    config = replace(
        DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, development_ratio=0.5, validation_ratio=0.25, test_ratio=0.25
    )
    plan = build_partition_plan("SPY", "1h", _timestamps(100), config=config)
    counts = {b.partition: b.bar_count for b in plan.bounds}
    assert counts[Partition.DEVELOPMENT] == 50
    assert counts[Partition.VALIDATION] == 25
    assert counts[Partition.TEST] == 25


def test_ratios_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1.0"):
        ResearchIntelligenceConfig(development_ratio=0.5, validation_ratio=0.3, test_ratio=0.3)
