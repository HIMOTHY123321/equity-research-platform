from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.lifecycle import compute_freshness, determine_lifecycle
from app.support_resistance.schemas import (
    BreakEvent,
    InteractionType,
    LevelKind,
    ZoneInteraction,
    ZoneLifecycle,
)
from tests.unit.support_resistance.conftest import hourly

CONFIG = SupportResistanceConfig(weakened_after_independent_interactions=4, stale_after_bars=10)


def _simple_candles(n):
    result = []
    for h in range(n):
        result.append(hourly(17, 9 + h, 190, 191, 189, 190.5))
    return result


def interaction(hour_index, candles, interaction_type=InteractionType.TOUCH, is_independent=True):
    return ZoneInteraction(
        timestamp=candles[hour_index].timestamp,
        interaction_type=interaction_type,
        high=191,
        low=189,
        close=190.5,
        distance=0.1,
        is_independent=is_independent,
    )


def test_bars_since_created_is_zero_indexed_span():
    candles = _simple_candles(5)
    freshness = compute_freshness(candles, [], None)
    assert freshness.bars_since_created == 4


def test_bars_since_last_touch():
    candles = _simple_candles(5)
    touch = interaction(2, candles)
    freshness = compute_freshness(candles, [touch], None)
    assert freshness.bars_since_last_touch == 2  # index2 -> latest index4 -> 2 bars


def test_bars_since_last_rejection_ignores_plain_touches():
    candles = _simple_candles(5)
    interactions = [
        interaction(1, candles, InteractionType.TOUCH),
        interaction(3, candles, InteractionType.REJECTION),
    ]
    freshness = compute_freshness(candles, interactions, None)
    assert freshness.bars_since_last_rejection == 1


def test_bars_since_break():
    candles = _simple_candles(5)
    break_event = BreakEvent(
        direction=LevelKind.RESISTANCE,
        break_price=195,
        first_broken_at=candles[3].timestamp,
        zone_lower_bound=190,
        zone_upper_bound=191,
    )
    freshness = compute_freshness(candles, [], break_event)
    assert freshness.bars_since_break == 1


def test_non_independent_interactions_do_not_affect_freshness():
    candles = _simple_candles(5)
    interactions = [interaction(4, candles, InteractionType.TOUCH, is_independent=False)]
    freshness = compute_freshness(candles, interactions, None)
    assert freshness.bars_since_last_touch is None  # the only interaction isn't independent


# ---- lifecycle state determination -----------------------------------------


def _freshness(bars_since_created=10, bars_since_last_touch=None):
    from app.support_resistance.schemas import ZoneFreshness

    return ZoneFreshness(
        bars_since_created=bars_since_created,
        bars_since_last_touch=bars_since_last_touch,
        bars_since_last_rejection=None,
        bars_since_break=None,
    )


def test_active_when_never_touched_and_fresh():
    result = determine_lifecycle(
        _freshness(bars_since_created=2), independent_interaction_count=0, is_broken=False, config=CONFIG
    )
    assert result == ZoneLifecycle.ACTIVE


def test_tested_after_first_independent_interaction():
    result = determine_lifecycle(
        _freshness(bars_since_last_touch=1), independent_interaction_count=1, is_broken=False, config=CONFIG
    )
    assert result == ZoneLifecycle.TESTED


def test_weakened_after_threshold_interactions():
    result = determine_lifecycle(
        _freshness(bars_since_last_touch=1), independent_interaction_count=4, is_broken=False, config=CONFIG
    )
    assert result == ZoneLifecycle.WEAKENED


def test_broken_takes_precedence_over_everything():
    result = determine_lifecycle(
        _freshness(bars_since_last_touch=1), independent_interaction_count=10, is_broken=True, config=CONFIG
    )
    assert result == ZoneLifecycle.BROKEN


def test_stale_when_no_recent_interaction():
    result = determine_lifecycle(
        _freshness(bars_since_created=50, bars_since_last_touch=None),
        independent_interaction_count=0,
        is_broken=False,
        config=CONFIG,
    )
    assert result == ZoneLifecycle.STALE


def test_stale_uses_last_touch_when_available():
    result = determine_lifecycle(
        _freshness(bars_since_created=50, bars_since_last_touch=50),
        independent_interaction_count=2,
        is_broken=False,
        config=CONFIG,
    )
    assert result == ZoneLifecycle.STALE
