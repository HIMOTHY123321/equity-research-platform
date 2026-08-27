"""Chronological development/validation/test partitions (#5). A dataset is
split into three contiguous, time-ordered chunks by bar count -- never
randomly shuffled, and never re-split per query to go looking for a nicer
result. This is architecture only: nothing in this package optimizes
anything using this split yet (#33) -- it exists so the same rule can never
be evaluated against all of its own data and then declared "validated."
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import DatasetPartitionPlan, Partition, PartitionBounds


def build_partition_plan(
    symbol: str,
    timeframe: str,
    timestamps: list[datetime],
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> DatasetPartitionPlan:
    """`timestamps` must already be chronologically sorted (the caller's
    candle series is), and every bar contributes to exactly one partition."""
    if not timestamps:
        raise ValueError(f"cannot build a partition plan for {symbol} {timeframe} with zero bars")
    if any(timestamps[i] > timestamps[i + 1] for i in range(len(timestamps) - 1)):
        raise ValueError(
            "timestamps must be chronologically sorted -- partitions are never built from shuffled data"
        )

    n = len(timestamps)
    dev_count = round(n * config.development_ratio)
    val_count = round(n * config.validation_ratio)
    # The test partition absorbs any rounding remainder so every bar is
    # accounted for and the three counts always sum to n exactly.
    test_count = n - dev_count - val_count

    bounds: list[PartitionBounds] = []
    cursor = 0
    for partition, count in (
        (Partition.DEVELOPMENT, dev_count),
        (Partition.VALIDATION, val_count),
        (Partition.TEST, test_count),
    ):
        if count <= 0:
            continue
        chunk = timestamps[cursor : cursor + count]
        bounds.append(
            PartitionBounds(partition=partition, start=chunk[0], end=chunk[-1], bar_count=len(chunk))
        )
        cursor += count

    return DatasetPartitionPlan(
        symbol=symbol,
        timeframe=timeframe,
        development_ratio=config.development_ratio,
        validation_ratio=config.validation_ratio,
        test_ratio=config.test_ratio,
        bounds=bounds,
    )


def partition_for_timestamp(plan: DatasetPartitionPlan, timestamp: datetime) -> Optional[Partition]:
    """Which partition a timestamp falls in, or None if it's outside the
    plan's covered range entirely (e.g. a bar from a later re-fetch)."""
    for b in plan.bounds:
        if b.start <= timestamp <= b.end:
            return b.partition
    return None
