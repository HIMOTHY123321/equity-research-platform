from datetime import timedelta

from app.market_structure.schemas import Direction, SwingType
from app.schemas.market_data import Candle, MarketSession, Timeframe
from app.setup_detection.detectors import liquidity_sweep
from tests.unit.setup_detection.conftest import build_inputs, load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _append_bar(after: Candle, high, low, close, volume=50_000):
    return Candle(
        symbol=after.symbol,
        timeframe=Timeframe.ONE_HOUR,
        timestamp=after.timestamp + timedelta(hours=1),
        session=MarketSession.REGULAR,
        open=(high + low) / 2,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_bullish_sweep_wicks_below_a_known_swing_low_and_closes_back_above():
    inputs0 = build_inputs(SPY_1H, daily_candles=SPY_1D)
    structure0 = inputs0.structure_by_timeframe[inputs0.timeframe]
    # The lowest confirmed swing low: a wick that only dips just beneath it
    # can't also breach any other (higher) swing low, so exactly one
    # candidate should reference it -- unlike the latest swing low, which
    # sits above several others and made this test's earlier version flaky.
    lows = [s for s in structure0.swings if s.type == SwingType.LOW]
    target = min(lows, key=lambda s: s.price)

    sweep = _append_bar(SPY_1H[-1], high=target.price + 1.0, low=target.price - 0.5, close=target.price + 0.5)
    as_of = sweep.timestamp + timedelta(hours=1)
    inputs = build_inputs(SPY_1H + [sweep], daily_candles=SPY_1D, as_of=as_of)

    matches = [c for c in liquidity_sweep.detect(inputs) if c.direction == Direction.BULLISH]
    assert matches, "expected a bullish liquidity sweep candidate"
    assert any(m.reference_price == target.price for m in matches)
    for match in matches:
        for check in match.hard_checks:
            if check.code == "level_confirmed_before_sweep":
                assert check.passed


def test_sweep_requires_the_level_to_have_been_confirmed_before_the_candle():
    """The anti-lookahead invariant this detector exists to enforce (#10):
    a swing whose confirmed_at is AFTER the sweeping candle can never be
    used as that candle's sweep reference."""
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)
    structure = inputs.structure_by_timeframe[inputs.timeframe]

    for candidate in liquidity_sweep.detect(inputs):
        matching_swing = next(
            s
            for s in structure.swings
            if s.price == candidate.reference_price and s.pivot_timestamp == candidate.reference_timestamp
        )
        assert matching_swing.confirmed_at < candidate.candidate_candle_timestamp


def test_same_swing_never_produces_two_candidates():
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)
    candidates = liquidity_sweep.detect(inputs)
    keys = [(c.direction, c.reference_price, c.reference_timestamp) for c in candidates]
    assert len(keys) == len(set(keys))
