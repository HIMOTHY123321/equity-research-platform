from datetime import timedelta

from app.market_structure.schemas import Direction
from app.setup_detection.detectors import gap_fill
from tests.unit.setup_detection.conftest import build_inputs, flat_session, hour_bar


def _gapped_session(gap_open, closes):
    day17 = flat_session(17, price=100.0)
    day18 = []
    prev_open = gap_open
    for hour, close in zip(range(10, 10 + len(closes)), closes):
        day18.append(
            hour_bar(
                18,
                hour,
                max(prev_open, close) + 0.5,
                min(prev_open, close) - 0.5,
                open=prev_open,
                close=close,
            )
        )
        prev_open = close
    return day17 + day18


def test_gap_up_that_trades_back_through_previous_close_triggers():
    # Previous close = 100.0; gap up to 102, then price falls back through 100.
    candles = _gapped_session(gap_open=102.0, closes=[102.0, 101.0, 99.5])
    inputs = build_inputs(candles, as_of=candles[-1].timestamp + timedelta(hours=1))
    matches = gap_fill.detect(inputs)
    assert matches
    candidate = matches[0]
    assert candidate.direction == Direction.BEARISH  # the fill move is downward
    assert candidate.current_state.value == "triggered"
    assert candidate.metadata["full_fill"] is True
    assert candidate.triggered_at is not None


def test_gap_up_that_never_fills_stays_qualified_and_tracks_partial_fill():
    candles = _gapped_session(gap_open=102.0, closes=[102.0, 102.2, 102.5])
    inputs = build_inputs(candles, as_of=candles[-1].timestamp + timedelta(hours=1))
    matches = gap_fill.detect(inputs)
    assert matches
    candidate = matches[0]
    assert candidate.current_state.value == "qualified"
    assert candidate.metadata["full_fill"] is False
    assert candidate.triggered_at is None


def test_small_gap_below_minimum_produces_no_candidate():
    inputs = build_inputs(_gapped_session(gap_open=100.1, closes=[100.1, 100.2, 100.3]))
    assert gap_fill.detect(inputs) == []
