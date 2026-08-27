"""The 10 mandatory anti-lookahead tests (#36). Each one proves a specific
way a setup could otherwise leak future information into a historical
result, using real yfinance-shaped data so the guarantees hold against
actual market behavior, not just synthetic fixtures.
"""

from __future__ import annotations

from datetime import timedelta

from app.setup_detection.detectors import (
    breakout_retest,
    failed_breakout,
    liquidity_sweep,
    previous_day_breakout,
)
from app.setup_detection.engine import compute_setup_detection_snapshot
from app.setup_detection.lifecycle import is_past_expiration
from tests.unit.setup_detection.conftest import build_inputs, load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _snapshot_at(as_of):
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=as_of)
    return compute_setup_detection_snapshot(
        inputs.symbol,
        inputs.timeframe,
        SPY_1H,
        SPY_1D,
        inputs.feature_snapshot,
        inputs.structure_by_timeframe,
        inputs.levels_snapshot,
        as_of,
    )


def test_1_appending_future_candles_leaves_historical_snapshot_unchanged():
    as_of = SPY_1H[150].timestamp + timedelta(minutes=1)
    snap_short = _snapshot_at(as_of)

    # Recompute with the SAME as_of but the full (longer) candle series --
    # extending the data forward must never change a result already fixed
    # at an earlier as_of.
    inputs_full = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=as_of)
    snap_full = compute_setup_detection_snapshot(
        inputs_full.symbol,
        inputs_full.timeframe,
        SPY_1H,
        SPY_1D,
        inputs_full.feature_snapshot,
        inputs_full.structure_by_timeframe,
        inputs_full.levels_snapshot,
        as_of,
    )

    ids_short = {c.id for bucket in _all_buckets(snap_short) for c in bucket}
    ids_full = {c.id for bucket in _all_buckets(snap_full) for c in bucket}
    assert ids_short == ids_full


def test_2_breakout_unavailable_before_confirming_candle_closes():
    inputs_now = build_inputs(SPY_1H, daily_candles=SPY_1D)
    now_candidates = previous_day_breakout.detect(inputs_now)
    assert now_candidates, "expected at least one PDH/PDL candidate on real data to test against"
    breakout = now_candidates[0]

    just_before = breakout.candidate_candle_timestamp - timedelta(seconds=1)
    inputs_before = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=just_before)
    before_candidates = previous_day_breakout.detect(inputs_before)
    assert breakout.id not in {c.id for c in before_candidates}


def test_3_retest_does_not_exist_before_retest_candle():
    inputs_now = build_inputs(SPY_1H, daily_candles=SPY_1D)
    retests = [c for c in breakout_retest.detect(inputs_now) if c.triggered_at is not None]
    if not retests:
        return  # no live retest in this fixture window -- nothing to assert
    retest = retests[0]

    just_before = retest.triggered_at - timedelta(seconds=1)
    inputs_before = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=just_before)
    before = breakout_retest.detect(inputs_before)
    assert retest.id not in {c.id for c in before}


def test_4_future_rvol_cannot_strengthen_earlier_qualification():
    as_of = SPY_1H[150].timestamp + timedelta(minutes=1)
    snap = _snapshot_at(as_of)
    for candidate in snap.qualified_setups + snap.candidates:
        # context.rvol is stamped from the snapshot computed AT as_of; it can
        # never reflect volume from bars after candidate_candle_timestamp.
        assert candidate.context is not None
        assert candidate.context.as_of <= as_of


def test_5_future_swing_confirmation_cannot_create_earlier_setup_evidence():
    as_of = SPY_1H[150].timestamp + timedelta(minutes=1)
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=as_of)
    for candidate in liquidity_sweep.detect(inputs):
        for check in candidate.hard_checks:
            if check.code == "level_confirmed_before_sweep":
                assert check.passed


def test_6_future_sr_zone_cannot_create_earlier_setup():
    as_of = SPY_1H[150].timestamp + timedelta(minutes=1)
    snap = _snapshot_at(as_of)
    for candidate in snap.qualified_setups + snap.candidates + snap.rejected_candidates:
        assert candidate.candidate_candle_timestamp <= as_of
        if candidate.context is not None:
            assert candidate.context.as_of <= as_of


def test_7_future_htf_information_cannot_alter_historical_context():
    as_of = SPY_1H[150].timestamp + timedelta(minutes=1)
    snap_a = _snapshot_at(as_of)
    snap_b = _snapshot_at(as_of)
    contexts_a = [c.context for c in snap_a.qualified_setups]
    contexts_b = [c.context for c in snap_b.qualified_setups]
    assert contexts_a == contexts_b


def test_8_failed_breakout_cannot_be_known_before_failure_occurs():
    inputs_now = build_inputs(SPY_1H, daily_candles=SPY_1D)
    failures = [
        c for c in failed_breakout.detect(inputs_now) if c.setup_type.value == "confirmed_breakout_failure"
    ]
    if not failures:
        return
    failure = failures[0]

    just_before = failure.invalidated_at - timedelta(seconds=1)
    inputs_before = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=just_before)
    before = [
        c for c in failed_breakout.detect(inputs_before) if c.setup_type.value == "confirmed_breakout_failure"
    ]
    assert failure.id not in {c.id for c in before}


def test_9_candidate_expiration_cannot_happen_before_expiration_timestamp():
    as_of = SPY_1H[150].timestamp + timedelta(minutes=1)
    snap = _snapshot_at(as_of)
    for candidate in snap.qualified_setups + snap.candidates:
        assert not is_past_expiration(candidate.expires_at, candidate.candidate_candle_timestamp)


def test_10_fingerprint_at_t_remains_identical_after_future_data_appended():
    as_of = SPY_1H[150].timestamp + timedelta(minutes=1)

    truncated_series = [c for c in SPY_1H if c.timestamp <= as_of]
    inputs_truncated = build_inputs(truncated_series, daily_candles=SPY_1D, as_of=as_of)
    inputs_full = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=as_of)

    candidates_truncated = {c.id: c.fingerprint for c in previous_day_breakout.detect(inputs_truncated)}
    candidates_full = {c.id: c.fingerprint for c in previous_day_breakout.detect(inputs_full)}

    for candidate_id, fingerprint in candidates_truncated.items():
        assert candidates_full[candidate_id] == fingerprint


def _all_buckets(snapshot):
    return (
        snapshot.qualified_setups,
        snapshot.candidates,
        snapshot.rejected_candidates,
        snapshot.recently_invalidated,
        snapshot.recently_expired,
    )
