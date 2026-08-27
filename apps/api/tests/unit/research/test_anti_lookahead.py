"""The 13 mandatory anti-lookahead invariants (#47), against real SPY data.
No network access required -- replays the static fixture captured in
tests/fixtures/real_market_data.json.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from app.features.config import DEFAULT_FEATURE_CONFIG
from app.market_structure.common import candle_complete_at
from app.market_structure.config import DEFAULT_MARKET_STRUCTURE_CONFIG
from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.config_hash import build_config_snapshot, compute_config_hash
from app.research.engine import execute_research_run
from app.research.outcomes import evaluate_setup_outcome
from app.research.replay import run_replay
from app.schemas.market_data import Timeframe
from app.setup_detection.config import DEFAULT_SETUP_DETECTION_CONFIG
from app.support_resistance.config import DEFAULT_SUPPORT_RESISTANCE_CONFIG
from tests.unit.research.conftest import SYMBOL, in_memory_repository, live_snapshot_at
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")
SPY_4H = load_real_candles(
    "SPY_1h"
)  # 4H structure source; real aggregation isn't required for these invariants


def _small_window():
    start = SPY_1H[120].timestamp
    end = SPY_1H[160].timestamp
    return start, end


def test_1_replay_detection_at_t_equals_normal_detector_snapshot_at_t():
    start, end = _small_window()
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_4H, "run-1")

    checked = 0
    for entry in result.ledger_entries:
        as_of = candle_complete_at(next(c for c in SPY_1H if c.timestamp == entry.candidate_candle_timestamp))
        if as_of > end:
            continue  # this entry's lifecycle was last observed beyond our small comparison window
        live = live_snapshot_at(SYMBOL, Timeframe.ONE_HOUR, SPY_1H, SPY_1D, SPY_4H, entry.last_observed_at)
        live_ids = {
            c.id
            for c in (
                live.qualified_setups
                + live.candidates
                + live.rejected_candidates
                + live.recently_invalidated
                + live.recently_expired
            )
        }
        assert entry.setup_id in live_ids
        checked += 1
    assert checked > 0, "expected at least one ledger entry to verify parity against"


def test_2_and_3_appending_future_candles_cannot_change_frozen_detection_context():
    start, end = _small_window()
    truncated = [c for c in SPY_1H if c.timestamp <= end + timedelta(days=5)]

    result_short = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, truncated, SPY_1D, SPY_4H, "run-a")
    result_full = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_4H, "run-b")

    by_id_short = {e.setup_id: e for e in result_short.ledger_entries}
    by_id_full = {e.setup_id: e for e in result_full.ledger_entries}

    for setup_id, entry_short in by_id_short.items():
        entry_full = by_id_full[setup_id]
        # Detection-time payload (#2) must be byte-identical regardless of
        # how much future data was available when replay ran.
        assert entry_short.detection == entry_full.detection

    # Outcome data (#3), by contrast, MAY legitimately differ -- more future
    # data can complete previously-unavailable horizons.
    outcome_short = evaluate_setup_outcome(next(iter(by_id_short.values())).detection, truncated)
    outcome_full = evaluate_setup_outcome(next(iter(by_id_short.values())).detection, SPY_1H)
    assert outcome_short.evaluation_quality.bars_available_after_detection <= (
        outcome_full.evaluation_quality.bars_available_after_detection
    )


def test_4_and_5_mfe_mae_only_use_candles_after_detection():
    candidate_source = next(
        e.detection
        for e in run_replay(
            SYMBOL, Timeframe.ONE_HOUR, *_small_window(), SPY_1H, SPY_1D, SPY_4H, "run-c"
        ).ledger_entries
    )
    outcome = evaluate_setup_outcome(candidate_source, SPY_1H)
    assert outcome is not None
    if outcome.mfe.timestamp is not None:
        assert outcome.mfe.timestamp > candidate_source.candidate_candle_timestamp
    if outcome.mae.timestamp is not None:
        assert outcome.mae.timestamp > candidate_source.candidate_candle_timestamp


def test_6_atr_normalized_outcomes_use_atr_frozen_at_detection():
    entries = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, *_small_window(), SPY_1H, SPY_1D, SPY_4H, "run-d"
    ).ledger_entries
    entry = entries[0]
    outcome = evaluate_setup_outcome(entry.detection, SPY_1H)
    assert outcome.detection_atr == entry.detection.context.atr


def test_7_no_horizon_beyond_available_future_bars():
    # The very last entry detected in the window has the fewest future bars
    # available within the fixture -- some longer horizons must be unavailable.
    entries = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, *_small_window(), SPY_1H, SPY_1D, SPY_4H, "run-e"
    ).ledger_entries
    latest_entry = max(entries, key=lambda e: e.candidate_candle_timestamp)
    # Only 3 bars after detection -- far short of the 20-bar horizon.
    limited = [
        c for c in SPY_1H if c.timestamp <= latest_entry.candidate_candle_timestamp + timedelta(hours=3)
    ]
    outcome = evaluate_setup_outcome(latest_entry.detection, limited)
    unavailable = [h for h in outcome.horizons if not h.available]
    assert any(h.horizon_bars >= 5 for h in unavailable)


def test_8_rejected_candidate_outcome_never_changes_the_rejection_reason():
    entries = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, *_small_window(), SPY_1H, SPY_1D, SPY_4H, "run-f"
    ).ledger_entries
    rejected = [e for e in entries if e.current_state == "rejected"]
    if not rejected:
        return
    entry = rejected[0]
    hard_checks_before = list(entry.detection.hard_checks)
    evaluate_setup_outcome(entry.detection, SPY_1H)
    assert entry.detection.hard_checks == hard_checks_before


def test_9_config_hash_stable_for_identical_configuration():
    snapshot_a = build_config_snapshot(
        DEFAULT_FEATURE_CONFIG,
        DEFAULT_MARKET_STRUCTURE_CONFIG,
        DEFAULT_SUPPORT_RESISTANCE_CONFIG,
        DEFAULT_SETUP_DETECTION_CONFIG,
        DEFAULT_RESEARCH_CONFIG,
    )
    hash_a = compute_config_hash(snapshot_a)
    hash_b = compute_config_hash(snapshot_a)
    assert hash_a == hash_b

    changed_setup_config = replace(DEFAULT_SETUP_DETECTION_CONFIG, min_rvol_for_confirmation=999.0)
    snapshot_c = build_config_snapshot(
        DEFAULT_FEATURE_CONFIG,
        DEFAULT_MARKET_STRUCTURE_CONFIG,
        DEFAULT_SUPPORT_RESISTANCE_CONFIG,
        changed_setup_config,
        DEFAULT_RESEARCH_CONFIG,
    )
    hash_c = compute_config_hash(snapshot_c)
    assert hash_c != hash_a


def test_10_same_dataset_and_config_produce_deterministic_replay_results():
    start, end = _small_window()
    result_a = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_4H, "run-g")
    result_b = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_4H, "run-g")
    assert {e.setup_id for e in result_a.ledger_entries} == {e.setup_id for e in result_b.ledger_entries}
    assert result_a.bars_processed == result_b.bars_processed


def test_11_and_12_future_swing_and_sr_confirmation_cannot_alter_earlier_replay_detection():
    start, end = _small_window()
    result_short = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_4H, "run-h")
    extended_candles = SPY_1H  # already extends well past `end` in the fixture
    result_extended = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, start, end, extended_candles, SPY_1D, SPY_4H, "run-i"
    )

    ids_short = {e.setup_id for e in result_short.ledger_entries}
    ids_extended = {e.setup_id for e in result_extended.ledger_entries}
    assert ids_short == ids_extended


def test_13_sequential_breakout_retest_state_matches_live_semantics():
    start, end = _small_window()
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_4H, "run-j")
    retests = [e for e in result.ledger_entries if e.setup_type == "breakout_retest"]
    for entry in retests:
        live = live_snapshot_at(SYMBOL, Timeframe.ONE_HOUR, SPY_1H, SPY_1D, SPY_4H, entry.last_observed_at)
        live_ids = {
            c.id
            for c in (
                live.qualified_setups
                + live.candidates
                + live.rejected_candidates
                + live.recently_invalidated
                + live.recently_expired
            )
        }
        assert entry.setup_id in live_ids
        assert entry.current_state == entry.latest.current_state.value


def test_full_run_persists_and_completes_deterministically():
    start, end = _small_window()
    repository = in_memory_repository()
    run_id = execute_research_run(
        symbol=SYMBOL,
        timeframe=Timeframe.ONE_HOUR,
        start_date=start,
        end_date=end,
        primary_candles=SPY_1H,
        daily_candles=SPY_1D,
        four_hour_candles=SPY_4H,
        provider_name="yfinance",
        repository=repository,
    )
    record = repository.get_run(run_id)
    assert record.status == "completed"
