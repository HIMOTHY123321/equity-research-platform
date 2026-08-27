import pytest

from app.support_resistance.breaks import detect_zone_break
from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.schemas import LevelKind
from tests.unit.support_resistance.conftest import hourly

DEFAULT_CONFIG = SupportResistanceConfig(break_tolerance_percent=0.0)
LOWER, UPPER = 189.98, 190.18


def test_resistance_close_break():
    candles = [
        hourly(17, 9, 190.0, 190.1, 189.9, 190.05),
        hourly(17, 10, 190.3, 190.4, 190.2, 190.35),  # closes above upper bound
    ]
    event = detect_zone_break(candles, LevelKind.RESISTANCE, LOWER, UPPER, DEFAULT_CONFIG)

    assert event is not None
    assert event.direction == LevelKind.RESISTANCE
    assert event.break_price == pytest.approx(190.35)
    assert event.first_broken_at == candles[1].timestamp


def test_support_close_break():
    lower, upper = 184.05, 184.32
    candles = [
        hourly(17, 9, 184.2, 184.3, 184.1, 184.2),
        hourly(17, 10, 183.9, 184.0, 183.7, 183.80),  # closes below lower bound
    ]
    event = detect_zone_break(candles, LevelKind.SUPPORT, lower, upper, DEFAULT_CONFIG)

    assert event is not None
    assert event.direction == LevelKind.SUPPORT
    assert event.break_price == pytest.approx(183.80)


def test_wick_only_move_does_not_break():
    candles = [hourly(17, 9, 190.1, 190.5, 190.0, 190.10)]  # high wicks above, close stays inside
    event = detect_zone_break(candles, LevelKind.RESISTANCE, LOWER, UPPER, DEFAULT_CONFIG)
    assert event is None


def test_exact_equality_does_not_break():
    candles = [hourly(17, 9, 190.0, 190.18, 189.9, 190.18)]  # close == upper bound exactly
    event = detect_zone_break(candles, LevelKind.RESISTANCE, LOWER, UPPER, DEFAULT_CONFIG)
    assert event is None


def test_tolerance_requires_close_beyond_the_configured_buffer():
    config = SupportResistanceConfig(break_tolerance_percent=1.0)  # threshold = 190.18 * 1.01 ~= 192.08
    within_tolerance = [hourly(17, 9, 190.5, 191.0, 190.3, 190.50)]
    beyond_tolerance = [hourly(17, 9, 193.0, 193.5, 192.8, 193.00)]

    assert detect_zone_break(within_tolerance, LevelKind.RESISTANCE, LOWER, UPPER, config) is None
    assert detect_zone_break(beyond_tolerance, LevelKind.RESISTANCE, LOWER, UPPER, config) is not None


def test_only_the_first_qualifying_close_is_recorded():
    candles = [
        hourly(17, 9, 190.3, 190.4, 190.2, 190.35),
        hourly(17, 10, 191.0, 191.1, 190.9, 191.05),
        hourly(17, 11, 192.0, 192.1, 191.9, 192.05),
    ]
    event = detect_zone_break(candles, LevelKind.RESISTANCE, LOWER, UPPER, DEFAULT_CONFIG)
    assert event.first_broken_at == candles[0].timestamp
    assert event.break_price == pytest.approx(190.35)


def test_no_break_when_price_never_reaches_zone():
    candles = [hourly(17, 9, 100.0, 101.0, 99.0, 100.5)]
    event = detect_zone_break(candles, LevelKind.RESISTANCE, LOWER, UPPER, DEFAULT_CONFIG)
    assert event is None
