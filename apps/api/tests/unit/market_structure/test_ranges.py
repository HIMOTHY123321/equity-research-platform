import pytest

from app.market_structure.common import StructureStatus
from app.market_structure.ranges import compute_active_range
from app.market_structure.schemas import SwingPoint, SwingType
from tests.conftest import et


def swing(type_, price, hour):
    return SwingPoint(
        type=type_,
        price=price,
        pivot_timestamp=et(2026, 8, 17, hour, 30),
        confirmed_at=et(2026, 8, 17, hour + 2, 30),
        left_bars=2,
        right_bars=2,
    )


def test_exact_range_values():
    swings = [swing(SwingType.HIGH, 190.0, 4), swing(SwingType.LOW, 180.0, 2)]
    result = compute_active_range(swings, latest_price=185.0)

    assert result.status == StructureStatus.OK
    assert result.high == pytest.approx(190.0)
    assert result.low == pytest.approx(180.0)
    assert result.midpoint == pytest.approx(185.0)
    assert result.width == pytest.approx(10.0)
    assert result.width_percent == pytest.approx(10.0 / 180.0 * 100)
    assert result.position_percent == pytest.approx(50.0)


def test_position_percent_at_extremes():
    swings = [swing(SwingType.HIGH, 200.0, 4), swing(SwingType.LOW, 100.0, 2)]

    at_low = compute_active_range(swings, latest_price=100.0)
    at_high = compute_active_range(swings, latest_price=200.0)

    assert at_low.position_percent == pytest.approx(0.0)
    assert at_high.position_percent == pytest.approx(100.0)


def test_uses_most_recent_swing_of_each_type():
    swings = [
        swing(SwingType.HIGH, 150.0, 0),
        swing(SwingType.LOW, 100.0, 2),
        swing(SwingType.HIGH, 190.0, 4),  # most recent high
        swing(SwingType.LOW, 120.0, 6),  # most recent low
    ]
    result = compute_active_range(swings, latest_price=150.0)

    assert result.high == pytest.approx(190.0)
    assert result.low == pytest.approx(120.0)


def test_insufficient_data_with_no_highs():
    swings = [swing(SwingType.LOW, 100.0, 0)]
    result = compute_active_range(swings, latest_price=105.0)
    assert result.status == StructureStatus.INSUFFICIENT_DATA


def test_insufficient_data_with_no_lows():
    swings = [swing(SwingType.HIGH, 100.0, 0)]
    result = compute_active_range(swings, latest_price=95.0)
    assert result.status == StructureStatus.INSUFFICIENT_DATA


def test_missing_latest_price_leaves_position_percent_unavailable():
    swings = [swing(SwingType.HIGH, 190.0, 4), swing(SwingType.LOW, 180.0, 2)]
    result = compute_active_range(swings, latest_price=None)
    assert result.status == StructureStatus.OK
    assert result.position_percent is None
