from app.market_structure.common import candle_complete_at
from app.market_structure.schemas import Direction
from app.research.replay import run_replay
from app.schemas.market_data import Timeframe
from app.setup_detection.detectors import trend_pullback
from app.setup_detection.detectors.trend_pullback import _episode_start_index
from tests.unit.research.conftest import SYMBOL, live_snapshot_at
from tests.unit.setup_detection.conftest import build_inputs, flat_session, hour_bar, load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")
SPY_4H = load_real_candles("SPY_1h")  # 4H structure source; real aggregation isn't required here


def test_never_flags_a_pullback_when_the_structural_invalidation_level_is_broken():
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)

    for candidate in trend_pullback.detect(inputs):
        no_break_check = next(
            c for c in candidate.hard_checks if c.code == "structural_invalidation_not_broken"
        )
        assert no_break_check.passed, "a candidate should never be produced with a broken invalidation level"


def test_hard_checks_reflect_the_latest_bar_even_though_identity_is_the_episode_start():
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)
    latest = inputs.candles[-1]
    for candidate in trend_pullback.detect(inputs):
        # Identity may now be an earlier bar (the episode's start) -- never
        # later than "now", and evidence is always evaluated against the
        # current bar, not backdated to the episode start.
        assert candidate.candidate_candle_timestamp <= latest.timestamp
        no_break_check = next(
            c for c in candidate.hard_checks if c.code == "structural_invalidation_not_broken"
        )
        assert no_break_check.actual == latest.close


def test_skipped_entirely_without_enough_structural_context():
    candles = flat_session(17, price=100.0) + flat_session(18, price=100.0)
    inputs = build_inputs(candles)
    assert trend_pullback.detect(inputs) == []


# ---------------------------------------------------------------------------
# Regression tests for the episode-identity fix (Phase 8 #0). The bug: a
# retracement held near the same reference zone for many consecutive bars
# was minting a brand-new candidate every bar, because identity was anchored
# to "whichever bar is latest" rather than to when the episode began.
# ---------------------------------------------------------------------------


def test_episode_start_index_walks_back_through_an_unbroken_streak():
    day = flat_session(17, price=100.0)
    candles = day + [
        hour_bar(18, h, 100.5, 99.5, close=100.0) for h in range(9, 16)
    ]  # 7 bars, all closing well above a level of 90
    idx = _episode_start_index(candles, Direction.BULLISH, 90.0, candles[0].timestamp)
    assert (
        candles[idx].timestamp == candles[0].timestamp
    )  # walks all the way back to the earliest eligible bar


def test_episode_start_index_stops_at_a_structural_break():
    candles = [hour_bar(17, h, 100.5, 99.5, close=100.0) for h in range(9, 13)]
    candles += [hour_bar(17, 13, 89.0, 87.0, close=88.0)]  # a genuine close-based break of level=90
    candles += [hour_bar(17, 14, 100.5, 99.5, close=100.0)]  # reclaimed
    idx = _episode_start_index(candles, Direction.BULLISH, 90.0, candles[0].timestamp)
    assert candles[idx].timestamp == candles[-1].timestamp  # the break resets the episode to the reclaim bar


def test_episode_start_index_never_precedes_the_swings_own_pivot():
    candles = [hour_bar(17, h, 100.5, 99.5, close=100.0) for h in range(9, 16)]
    pivot_ts = candles[3].timestamp  # the swing didn't exist as a value before this instant
    idx = _episode_start_index(candles, Direction.BULLISH, 90.0, pivot_ts)
    assert candles[idx].timestamp == pivot_ts


def test_same_pullback_over_multiple_bars_produces_one_stable_setup_id():
    idx0 = next(i for i, c in enumerate(SPY_1H) if str(c.timestamp) == "2026-08-12 09:00:00-04:00")
    ids_seen = set()
    for offset in range(3):
        candle = SPY_1H[idx0 + offset]
        as_of = candle_complete_at(candle)
        inputs = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=as_of)
        for candidate in trend_pullback.detect(inputs):
            if candidate.direction == Direction.BULLISH:
                ids_seen.add(candidate.id)
    assert len(ids_seen) == 1, f"expected one stable episode id across 3 consecutive bars, got {ids_seen}"


def test_historical_replay_produces_no_duplicate_pullback_ids_for_a_held_retracement():
    idx0 = next(i for i, c in enumerate(SPY_1H) if str(c.timestamp) == "2026-08-12 09:00:00-04:00")
    start, end = SPY_1H[idx0].timestamp, SPY_1H[idx0 + 2].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_4H, "pullback-dup-check")
    bullish_pullbacks = [
        e for e in result.ledger_entries if e.setup_type == "trend_pullback" and e.direction == "bullish"
    ]
    assert len(bullish_pullbacks) == 1


def test_live_snapshot_and_replay_agree_on_the_same_pullback_id():
    idx0 = next(i for i, c in enumerate(SPY_1H) if str(c.timestamp) == "2026-08-12 09:00:00-04:00")
    start, end = SPY_1H[idx0].timestamp, SPY_1H[idx0 + 2].timestamp
    result = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_4H, "pullback-parity-check"
    )

    checked = 0
    for entry in result.ledger_entries:
        if entry.setup_type != "trend_pullback" or entry.direction != "bullish":
            continue
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
    assert checked > 0, "expected at least one bullish pullback ledger entry to verify parity against"


def test_expiration_is_not_already_past_when_a_fresh_episode_first_qualifies():
    idx0 = next(i for i, c in enumerate(SPY_1H) if str(c.timestamp) == "2026-08-12 09:00:00-04:00")
    as_of = candle_complete_at(SPY_1H[idx0])
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=as_of)
    for candidate in trend_pullback.detect(inputs):
        if candidate.current_state.value == "qualified":
            assert candidate.expires_at is not None
            assert candidate.expires_at > as_of


def test_invalidation_criteria_and_reference_timestamp_are_still_populated():
    # The fix only changes candidate_candle_timestamp/identity -- reference_timestamp
    # (the swing pivot) and invalidation_criteria are untouched by it.
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)
    for candidate in trend_pullback.detect(inputs):
        assert candidate.invalidation_criteria
        assert candidate.reference_timestamp is not None


def test_episode_identity_never_references_a_bar_after_as_of():
    idx0 = next(i for i, c in enumerate(SPY_1H) if str(c.timestamp) == "2026-08-12 10:30:00-04:00")
    as_of = candle_complete_at(SPY_1H[idx0])
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D, as_of=as_of)
    for candidate in trend_pullback.detect(inputs):
        assert candidate.candidate_candle_timestamp <= as_of
