"""Phase 12.2 (#N): provider latency measurement -- for every normalized
event, transport_latency = received_at - source_timestamp. Tracked by event
type/symbol/provider so a real observed number backs any freshness/latency
claim shown in the UI, never an assumption that WebSocket transport implies
low latency.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class LatencySummary:
    event_type: str
    symbol: str
    provider: str
    count: int
    median_seconds: float
    p95_seconds: float
    p99_seconds: float
    max_seconds: float


class LatencyTracker:
    """A small, bounded-memory rolling sample per (event_type, symbol,
    provider) key -- oldest samples are dropped once max_samples_per_key is
    reached (#AB: bounded, never unbounded growth)."""

    def __init__(self, max_samples_per_key: int = 500) -> None:
        self._max = max_samples_per_key
        self._samples: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    def record(self, event_type: str, symbol: str, provider: str, latency_seconds: float) -> None:
        key = (event_type, symbol, provider)
        bucket = self._samples[key]
        bucket.append(max(latency_seconds, 0.0))
        if len(bucket) > self._max:
            del bucket[0]

    def summary(self) -> list[LatencySummary]:
        result: list[LatencySummary] = []
        for (event_type, symbol, provider), samples in self._samples.items():
            if not samples:
                continue
            ordered = sorted(samples)
            result.append(
                LatencySummary(
                    event_type=event_type,
                    symbol=symbol,
                    provider=provider,
                    count=len(ordered),
                    median_seconds=_percentile(ordered, 50),
                    p95_seconds=_percentile(ordered, 95),
                    p99_seconds=_percentile(ordered, 99),
                    max_seconds=ordered[-1],
                )
            )
        return result


def _percentile(sorted_values: list[float], pct: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    fraction = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction
