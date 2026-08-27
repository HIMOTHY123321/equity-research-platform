from app.market_structure.schemas import Direction
from app.setup_detection.detectors import resistance_rejection
from app.support_resistance.schemas import InteractionType
from tests.unit.setup_detection.conftest import build_inputs, load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def test_candidates_only_come_from_real_independent_rejection_interactions():
    """Reuses Phase 5's own rejection events (#12) rather than an
    independent wick/close rule -- every candidate must trace back to a
    real ZoneInteraction on the zone it references."""
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)
    candidates = resistance_rejection.detect(inputs)

    for candidate in candidates:
        assert candidate.direction == Direction.BEARISH
        matching_zone = next(
            z
            for z in inputs.levels_snapshot.active_resistance_zones
            if z.representative_price == candidate.reference_price
        )
        rejections = [
            i
            for i in matching_zone.interactions
            if i.interaction_type == InteractionType.REJECTION and i.is_independent
        ]
        assert any(r.timestamp == candidate.candidate_candle_timestamp for r in rejections)


def test_no_candidate_for_a_zone_with_zero_independent_rejections():
    inputs = build_inputs(SPY_1H, daily_candles=SPY_1D)
    zones_without_rejection = [
        z
        for z in inputs.levels_snapshot.active_resistance_zones
        if not any(
            i.interaction_type == InteractionType.REJECTION and i.is_independent for i in z.interactions
        )
    ]
    candidates = resistance_rejection.detect(inputs)
    referenced_prices = {c.reference_price for c in candidates}
    for zone in zones_without_rejection:
        assert zone.representative_price not in referenced_prices
