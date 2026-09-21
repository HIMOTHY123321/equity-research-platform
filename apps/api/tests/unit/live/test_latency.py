"""Phase 12.2 (#N): LatencyTracker -- median/p95/p99/max per (event_type,
symbol, provider), bounded memory."""

from __future__ import annotations

from app.live.latency import LatencyTracker


def test_summary_is_empty_with_no_samples():
    tracker = LatencyTracker()
    assert tracker.summary() == []


def test_records_percentiles_per_key():
    tracker = LatencyTracker()
    for i in range(1, 101):
        tracker.record("trade", "SPY", "massive", i / 100)  # 0.01 .. 1.00

    summary = tracker.summary()
    assert len(summary) == 1
    entry = summary[0]
    assert entry.event_type == "trade"
    assert entry.symbol == "SPY"
    assert entry.provider == "massive"
    assert entry.count == 100
    assert abs(entry.median_seconds - 0.505) < 1e-9
    assert entry.max_seconds == 1.0
    assert entry.p95_seconds >= entry.median_seconds
    assert entry.p99_seconds >= entry.p95_seconds


def test_different_keys_are_tracked_independently():
    tracker = LatencyTracker()
    tracker.record("trade", "SPY", "massive", 0.1)
    tracker.record("quote", "SPY", "massive", 0.2)
    tracker.record("trade", "NVDA", "massive", 0.3)

    summary = {(e.event_type, e.symbol): e for e in tracker.summary()}
    assert len(summary) == 3
    assert summary[("trade", "SPY")].max_seconds == 0.1
    assert summary[("quote", "SPY")].max_seconds == 0.2
    assert summary[("trade", "NVDA")].max_seconds == 0.3


def test_negative_latency_is_clamped_to_zero():
    # A clock skew between received_at and source_timestamp should never
    # report an impossible negative latency.
    tracker = LatencyTracker()
    tracker.record("trade", "SPY", "massive", -0.5)
    assert tracker.summary()[0].max_seconds == 0.0


def test_bounded_memory_drops_oldest_samples():
    tracker = LatencyTracker(max_samples_per_key=5)
    for i in range(10):
        tracker.record("trade", "SPY", "massive", float(i))
    entry = tracker.summary()[0]
    assert entry.count == 5
    # Only the newest 5 samples (5..9) should remain.
    assert entry.max_seconds == 9.0
