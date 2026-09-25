from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.alerts.dedup import condition_dedup_key, transition_dedup_key
from app.alerts.schemas import AlertType


def test_transition_dedup_key_is_stable_for_identical_inputs():
    a = transition_dedup_key("plan-1", "trans-1", AlertType.INVALIDATED)
    b = transition_dedup_key("plan-1", "trans-1", AlertType.INVALIDATED)
    assert a == b


def test_transition_dedup_key_differs_on_any_field():
    base = transition_dedup_key("plan-1", "trans-1", AlertType.INVALIDATED)
    assert transition_dedup_key("plan-2", "trans-1", AlertType.INVALIDATED) != base
    assert transition_dedup_key("plan-1", "trans-2", AlertType.INVALIDATED) != base
    assert transition_dedup_key("plan-1", "trans-1", AlertType.EXIT_CONDITIONS_MET) != base


def test_condition_dedup_key_collides_within_same_cooldown_bucket():
    t1 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(minutes=5)
    key1 = condition_dedup_key("SPY", AlertType.DATA_STALE, "freshness", t1)
    key2 = condition_dedup_key("SPY", AlertType.DATA_STALE, "freshness", t2)
    assert key1 == key2


def test_condition_dedup_key_differs_across_cooldown_buckets():
    t1 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(hours=2)
    key1 = condition_dedup_key("SPY", AlertType.DATA_STALE, "freshness", t1)
    key2 = condition_dedup_key("SPY", AlertType.DATA_STALE, "freshness", t2)
    assert key1 != key2


def test_condition_dedup_key_differs_by_identity():
    t1 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    key1 = condition_dedup_key("SPY", AlertType.CONDITION_PASSED, "cond-a", t1)
    key2 = condition_dedup_key("SPY", AlertType.CONDITION_PASSED, "cond-b", t1)
    assert key1 != key2


def test_condition_dedup_key_handles_naive_datetime():
    naive = datetime(2026, 1, 1, 10, 0)
    aware = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert condition_dedup_key("SPY", AlertType.DATA_STALE, "freshness", naive) == condition_dedup_key(
        "SPY", AlertType.DATA_STALE, "freshness", aware
    )
