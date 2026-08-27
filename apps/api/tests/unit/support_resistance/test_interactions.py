from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.interactions import detect_interactions
from app.support_resistance.schemas import InteractionType, LevelKind
from tests.unit.support_resistance.conftest import hourly

TOLERANCE = 1e-9
CONFIG = SupportResistanceConfig(touch_tolerance_percent=0.1, minimum_bars_between_independent_touches=3)

# Resistance zone: 189.98 - 190.18, representative price 190.08
LOWER, UPPER, REPRESENTATIVE = 189.98, 190.18, 190.08


def test_single_touch():
    candles = [hourly(17, 9, 189.5, 190.05, 189.4, 189.6)]  # high enters zone, stays under rep price...
    # construct clearer: high=190.05 (inside zone, below rep), close below rep -> touch or rejection?
    # Use a candle that overlaps but closes ABOVE representative price (no rejection), no wick above upper.
    candles = [hourly(17, 9, 190.0, 190.1, 189.99, 190.1)]
    result = detect_interactions(candles, LevelKind.RESISTANCE, LOWER, UPPER, REPRESENTATIVE, CONFIG)

    assert len(result) == 1
    assert result[0].interaction_type == InteractionType.TOUCH
    assert result[0].is_independent is True


def test_no_interaction_outside_tolerance():
    candles = [hourly(17, 9, 185.0, 185.5, 184.5, 185.2)]  # nowhere near the zone
    result = detect_interactions(candles, LevelKind.RESISTANCE, LOWER, UPPER, REPRESENTATIVE, CONFIG)
    assert result == []


def test_wick_breach_pokes_above_but_closes_back_above_representative():
    # high exceeds upper bound, close stays above representative price (not a rejection)
    candles = [hourly(17, 9, 190.1, 190.30, 190.05, 190.15)]
    result = detect_interactions(candles, LevelKind.RESISTANCE, LOWER, UPPER, REPRESENTATIVE, CONFIG)

    assert len(result) == 1
    assert result[0].interaction_type == InteractionType.WICK_BREACH


def test_rejection_closes_back_below_representative_price():
    candles = [hourly(17, 9, 190.1, 190.25, 189.70, 189.90)]  # pokes above, closes well below rep price
    result = detect_interactions(candles, LevelKind.RESISTANCE, LOWER, UPPER, REPRESENTATIVE, CONFIG)

    assert len(result) == 1
    assert result[0].interaction_type == InteractionType.REJECTION


def test_adjacent_candles_count_as_one_independent_interaction():
    candles = [
        hourly(17, 9, 190.0, 190.1, 189.9, 190.05),
        hourly(17, 10, 190.0, 190.1, 189.9, 190.05),
        hourly(17, 11, 190.0, 190.1, 189.9, 190.05),
    ]
    result = detect_interactions(candles, LevelKind.RESISTANCE, LOWER, UPPER, REPRESENTATIVE, CONFIG)

    assert len(result) == 3  # all recorded...
    assert [r.is_independent for r in result] == [True, False, False]  # ...but only the first is independent


def test_separated_interactions_count_independently():
    candles = [
        hourly(17, 9, 190.0, 190.1, 189.9, 190.05),
        hourly(17, 10, 185.0, 185.1, 184.9, 185.0),  # away from zone, no interaction
        hourly(17, 11, 185.0, 185.1, 184.9, 185.0),
        hourly(17, 12, 185.0, 185.1, 184.9, 185.0),
        hourly(17, 13, 190.0, 190.1, 189.9, 190.05),  # far enough later (4 bars) -> independent again
    ]
    result = detect_interactions(candles, LevelKind.RESISTANCE, LOWER, UPPER, REPRESENTATIVE, CONFIG)

    assert len(result) == 2
    assert all(r.is_independent for r in result)


def test_stop_at_excludes_candles_at_or_after_the_break():
    candles = [
        hourly(17, 9, 190.0, 190.1, 189.9, 190.05),
        hourly(17, 10, 190.5, 190.6, 190.4, 190.55),  # would be a break candle
    ]
    result = detect_interactions(
        candles, LevelKind.RESISTANCE, LOWER, UPPER, REPRESENTATIVE, CONFIG, stop_at=candles[1].timestamp
    )
    assert len(result) == 1
    assert result[0].timestamp == candles[0].timestamp


def test_support_zone_mirrors_resistance_logic():
    # Support zone: 184.05 - 184.32, representative 184.18
    lower, upper, representative = 184.05, 184.32, 184.18
    rejection_candle = [hourly(17, 9, 184.2, 184.40, 184.00, 184.35)]  # pokes below, closes back above rep
    result = detect_interactions(rejection_candle, LevelKind.SUPPORT, lower, upper, representative, CONFIG)

    assert len(result) == 1
    assert result[0].interaction_type == InteractionType.REJECTION
