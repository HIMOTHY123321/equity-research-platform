from app.market_structure.freshness import compute_freshness
from app.market_structure.schemas import (
    BreakOfStructureEvent,
    ChangeOfCharacterEvent,
    Direction,
    SwingPoint,
    SwingType,
)
from tests.conftest import et
from tests.unit.market_structure.conftest import bars


def swing(type_, price, hour):
    return SwingPoint(
        type=type_,
        price=price,
        pivot_timestamp=et(2026, 8, 17, hour, 30),
        confirmed_at=et(2026, 8, 17, hour + 2, 30),
        left_bars=2,
        right_bars=2,
    )


def test_exact_bars_since_counts():
    candles = bars([(h, 10, 5) for h in range(10)])  # 10 candles, indices 0..9
    high = swing(SwingType.HIGH, 15, hour=6)  # index 6 -> 3 bars before the latest (index 9)
    low = swing(SwingType.LOW, 5, hour=8)  # index 8 -> 1 bar before the latest

    result = compute_freshness(candles, high, low, None, None, None)

    assert result.bars_since_last_swing_high == 3
    assert result.bars_since_last_swing_low == 1


def test_event_on_the_latest_candle_is_zero_bars_ago():
    candles = bars([(h, 10, 5) for h in range(5)])
    bos = BreakOfStructureEvent(
        direction=Direction.BULLISH,
        broken_level=10,
        broken_swing_timestamp=candles[0].timestamp,
        break_timestamp=candles[-1].timestamp,
        distance_beyond_level=1,
    )
    result = compute_freshness(candles, None, None, bos, None, None)
    assert result.bars_since_last_bullish_bos == 0


def test_missing_event_returns_none():
    candles = bars([(h, 10, 5) for h in range(5)])
    result = compute_freshness(candles, None, None, None, None, None)

    assert result.bars_since_last_swing_high is None
    assert result.bars_since_last_swing_low is None
    assert result.bars_since_last_bullish_bos is None
    assert result.bars_since_last_bearish_bos is None
    assert result.bars_since_last_choch is None


def test_choch_freshness():
    candles = bars([(h, 10, 5) for h in range(6)])
    choch = ChangeOfCharacterEvent(
        direction=Direction.BEARISH,
        prior_structure=Direction.BULLISH,
        broken_level=8,
        break_timestamp=candles[4].timestamp,
        reference_swing_timestamp=candles[1].timestamp,
    )
    result = compute_freshness(candles, None, None, None, None, choch)
    assert result.bars_since_last_choch == 1  # index4, latest index5 -> 1 bar ago
