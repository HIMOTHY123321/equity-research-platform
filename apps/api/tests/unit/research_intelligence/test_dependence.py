import datetime as dt

import pytest

from app.research_intelligence.dependence import (
    block_bootstrap_confidence_interval,
    compare_bootstrap_methods,
    detect_overlap,
)
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")


def _entry(template, setup_id, timestamp):
    return template.model_copy(update={"setup_id": setup_id, "candidate_candle_timestamp": timestamp})


def _build_template_entry():
    from app.research.replay import run_replay

    SPY_1D = load_real_candles("SPY_1d")
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "dependence-test")
    return result.ledger_entries[0]


# Built once at import time -- every test only needs a valid SetupLedgerEntry
# shape to model_copy() from, not a fresh replay run each time.
_TEMPLATE_ENTRY = _build_template_entry()


def _template_entry():
    return _TEMPLATE_ENTRY


def test_no_overlap_when_setups_are_spaced_beyond_the_horizon():
    template = _template_entry()
    # 1H bars, horizon=5 bars -> a window of 5 hours. Setups 10 hours apart
    # never overlap.
    t0 = SPY_1H[0].timestamp
    entries = [
        _entry(template, "a", t0),
        _entry(template, "b", t0 + dt.timedelta(hours=10)),
    ]
    report = detect_overlap(entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert report.overlapping_pair_count == 0
    assert report.warning is None


def test_overlap_detected_when_setups_are_closer_than_the_horizon():
    template = _template_entry()
    t0 = SPY_1H[0].timestamp
    entries = [
        _entry(template, "a", t0),
        _entry(template, "b", t0 + dt.timedelta(hours=2)),  # inside a 5-bar (5h) window
    ]
    report = detect_overlap(entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert report.overlapping_pair_count == 1
    assert report.overlapping_entry_count == 2
    assert report.overlap_fraction == 1.0
    assert report.warning is not None
    assert "OVERLAPPING OBSERVATIONS" in report.warning


def test_overlap_fraction_hand_calculated_with_three_entries():
    template = _template_entry()
    t0 = SPY_1H[0].timestamp
    entries = [
        _entry(template, "a", t0),
        _entry(template, "b", t0 + dt.timedelta(hours=1)),  # overlaps a (< 5h window)
        _entry(template, "c", t0 + dt.timedelta(hours=20)),  # far from b, no overlap
    ]
    report = detect_overlap(entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert report.sample_count == 3
    assert report.overlapping_pair_count == 1
    assert report.overlapping_entry_count == 2  # a and b, not c
    assert abs(report.overlap_fraction - (2 / 3)) < 1e-9


def test_empty_entries_produce_no_crash_and_no_warning():
    report = detect_overlap([], horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert report.sample_count == 0
    assert report.warning is None


def test_block_bootstrap_is_deterministic_for_the_same_seed():
    entries = [_template_entry().model_copy(update={"setup_id": f"e{i}"}) for i in range(60)]
    # Distinct timestamps across several distinct real trading days, values via outcome-free extraction.
    entries = [
        e.model_copy(update={"candidate_candle_timestamp": SPY_1H[0].timestamp + dt.timedelta(hours=i)})
        for i, e in enumerate(entries)
    ]

    def value_fn(entry):
        return float(hash(entry.setup_id) % 100) / 10.0

    result_a = block_bootstrap_confidence_interval(entries, value_fn, "mean", seed=3)
    result_b = block_bootstrap_confidence_interval(entries, value_fn, "mean", seed=3)
    assert result_a.lower == result_b.lower
    assert result_a.upper == result_b.upper
    assert result_a.method == "block_bootstrap_by_trading_day"


def test_weekly_block_bootstrap_is_deterministic_and_labeled_correctly():
    entries = [_template_entry().model_copy(update={"setup_id": f"e{i}"}) for i in range(60)]
    entries = [
        e.model_copy(update={"candidate_candle_timestamp": SPY_1H[0].timestamp + dt.timedelta(hours=i)})
        for i, e in enumerate(entries)
    ]

    def value_fn(entry):
        return float(hash(entry.setup_id) % 100) / 10.0

    result_a = block_bootstrap_confidence_interval(entries, value_fn, "mean", seed=5, block="weekly")
    result_b = block_bootstrap_confidence_interval(entries, value_fn, "mean", seed=5, block="weekly")
    assert result_a.lower == result_b.lower
    assert result_a.upper == result_b.upper
    assert result_a.method == "block_bootstrap_by_iso_week"


def test_unsupported_block_choice_is_rejected():
    entries = [_template_entry().model_copy(update={"setup_id": "e0"})]
    with pytest.raises(ValueError, match="unsupported block"):
        block_bootstrap_confidence_interval(entries, lambda e: 1.0, "mean", seed=1, block="monthly")


def test_compare_bootstrap_methods_returns_all_three_labeled_correctly():
    entries = [_template_entry().model_copy(update={"setup_id": f"e{i}"}) for i in range(60)]
    entries = [
        e.model_copy(update={"candidate_candle_timestamp": SPY_1H[0].timestamp + dt.timedelta(hours=i)})
        for i, e in enumerate(entries)
    ]

    def value_fn(entry):
        return float(hash(entry.setup_id) % 100) / 10.0

    results = compare_bootstrap_methods(entries, value_fn, "mean", seed=7)
    assert set(results.keys()) == {"naive", "daily_block", "weekly_block"}
    assert results["naive"].method == "percentile_bootstrap"
    assert results["daily_block"].method == "block_bootstrap_by_trading_day"
    assert results["weekly_block"].method == "block_bootstrap_by_iso_week"
    # All three share the same point estimate (same underlying values) even
    # though their intervals differ by resampling granularity.
    estimates = {r.point_estimate for r in results.values()}
    assert len(estimates) == 1


def test_compare_bootstrap_methods_below_minimum_sample_all_unavailable():
    entries = [_template_entry().model_copy(update={"setup_id": "only-one"})]
    results = compare_bootstrap_methods(entries, lambda e: 1.0, "mean", seed=1)
    assert all(not r.available for r in results.values())


def test_block_bootstrap_unavailable_below_minimum_sample():
    entries = [_template_entry().model_copy(update={"setup_id": "only-one"})]
    result = block_bootstrap_confidence_interval(entries, lambda e: 1.0, "mean", seed=1)
    assert result.available is False


def test_anti_leakage_block_grouping_is_a_pure_function_of_timestamp_only():
    """The block-key functions structurally cannot see outcome data -- each
    takes a bare timestamp, never a SetupLedgerEntry -- so which entries
    get resampled together can never depend on outcome magnitude."""
    import inspect

    from app.research_intelligence.dependence import _block_key_daily, _block_key_weekly

    assert list(inspect.signature(_block_key_daily).parameters) == ["timestamp"]
    assert list(inspect.signature(_block_key_weekly).parameters) == ["timestamp"]


def test_anti_leakage_block_bootstrap_availability_ignores_outcome_magnitude():
    entries = [_template_entry().model_copy(update={"setup_id": f"e{i}"}) for i in range(60)]
    entries = [
        e.model_copy(update={"candidate_candle_timestamp": SPY_1H[0].timestamp + dt.timedelta(hours=i)})
        for i, e in enumerate(entries)
    ]

    def real_value_fn(entry):
        return float(hash(entry.setup_id) % 100) / 10.0

    def fabricated_value_fn(entry):
        return 999999.0  # wildly different magnitude, same entries/timestamps

    real = block_bootstrap_confidence_interval(entries, real_value_fn, "mean", seed=3)
    fabricated = block_bootstrap_confidence_interval(entries, fabricated_value_fn, "mean", seed=3)
    # Same entries/timestamps -> same block structure -> identical
    # availability and iteration count, regardless of the values inside.
    assert real.available == fabricated.available
    assert real.iterations == fabricated.iterations
    assert real.method == fabricated.method
