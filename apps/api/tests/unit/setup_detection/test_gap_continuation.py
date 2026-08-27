from app.market_structure.schemas import Direction
from app.setup_detection.detectors import gap_continuation
from tests.unit.setup_detection.conftest import build_inputs, flat_session, hour_bar


def _gapped_session(gap_open, session_closes):
    """Day 17 is a flat 100.0 day (previous close = 100.0). Day 18 opens at
    `gap_open` and each subsequent bar closes at the corresponding value in
    `session_closes`."""
    day17 = flat_session(17, price=100.0)
    day18 = []
    first = True
    for hour, close in zip(range(10, 10 + len(session_closes)), session_closes):
        o = gap_open if first else session_closes[session_closes.index(close) - 1]
        day18.append(hour_bar(18, hour, max(o, close) + 0.5, min(o, close) - 0.5, open=o, close=close))
        first = False
    return day17 + day18


def test_gap_up_holding_qualifies_as_continuation():
    inputs = build_inputs(_gapped_session(gap_open=101.0, session_closes=[101.0, 101.5, 102.0]))
    matches = [c for c in gap_continuation.detect(inputs) if c.direction == Direction.BULLISH]
    assert matches
    assert matches[0].metadata["gap_percent"] > 0


def test_gap_that_has_mostly_filled_does_not_qualify():
    # Gap up to 101, but price crashes back to almost the previous close --
    # the gap structure is not holding.
    inputs = build_inputs(_gapped_session(gap_open=101.0, session_closes=[101.0, 100.05, 100.02]))
    matches = [c for c in gap_continuation.detect(inputs) if c.direction == Direction.BULLISH]
    assert matches, "the gap itself is still large enough to produce a candidate"
    assert matches[0].current_state.value == "rejected"
    fill_check = next(c for c in matches[0].hard_checks if c.code == "gap_not_mostly_filled")
    assert not fill_check.passed


def test_small_gap_below_minimum_produces_no_candidate():
    inputs = build_inputs(_gapped_session(gap_open=100.1, session_closes=[100.1, 100.2, 100.3]))
    assert not gap_continuation.detect(inputs)
