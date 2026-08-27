"""Replay-specific tests (#49) against real fixture data -- no network access."""

from __future__ import annotations

from app.research.replay import run_replay
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def test_replay_produces_at_least_one_setup_over_a_real_window():
    start, end = SPY_1H[100].timestamp, SPY_1H[200].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "r1")
    assert result.bars_processed > 0
    assert len(result.ledger_entries) > 0


def test_ledger_has_no_duplicate_setup_ids():
    start, end = SPY_1H[100].timestamp, SPY_1H[200].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "r2")
    ids = [e.setup_id for e in result.ledger_entries]
    assert len(ids) == len(set(ids))


def test_ledger_captures_rejected_candidates_not_only_qualified():
    start, end = SPY_1H[100].timestamp, SPY_1H[220].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "r3")
    states = {e.current_state for e in result.ledger_entries}
    assert "rejected" in states, "expected at least one rejected candidate over this window"


def test_lifecycle_transitions_are_chronologically_ordered_for_every_entry():
    start, end = SPY_1H[100].timestamp, SPY_1H[200].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "r4")
    for entry in result.ledger_entries:
        timestamps = [t.timestamp for t in entry.latest.transitions]
        assert timestamps == sorted(timestamps)


def test_first_seen_at_never_precedes_candidate_candle_timestamp_completion():
    start, end = SPY_1H[100].timestamp, SPY_1H[200].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "r5")
    for entry in result.ledger_entries:
        assert entry.first_seen_at >= entry.candidate_candle_timestamp


def test_narrower_window_never_reports_more_bars_than_wider_window():
    narrow = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, SPY_1H[150].timestamp, SPY_1H[160].timestamp, SPY_1H, SPY_1D, SPY_1H, "r6"
    )
    wide = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, SPY_1H[100].timestamp, SPY_1H[200].timestamp, SPY_1H, SPY_1D, SPY_1H, "r7"
    )
    assert narrow.bars_processed < wide.bars_processed
