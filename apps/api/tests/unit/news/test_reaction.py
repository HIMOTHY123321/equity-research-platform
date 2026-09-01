from app.news.reaction import classify_reaction_session, measure_market_reaction
from app.news.schemas import CatalystCategory, CatalystEvent, ReactionSession
from tests.unit.news.conftest import et
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")


def _event(timestamp, category=CatalystCategory.EARNINGS):
    return CatalystEvent(
        event_id="evt-test",
        primary_timestamp=timestamp,
        category=category,
        affected_symbols=("SPY",),
        contributing_article_ids=["a1"],
        source_count=1,
        earliest_published_at=timestamp,
        latest_update_at=timestamp,
        title="test event",
    )


def test_classify_reaction_session_regular_hours():
    # 2026-08-17 is a Monday; 14:30 UTC is 10:30 ET, regular session.
    assert classify_reaction_session(et(2026, 8, 17, 14, 30)) == ReactionSession.REGULAR


def test_classify_reaction_session_premarket():
    # 09:00 UTC is 05:00 ET, pre-market.
    assert classify_reaction_session(et(2026, 8, 17, 9, 0)) == ReactionSession.PRE_MARKET


def test_classify_reaction_session_after_hours():
    # 22:00 UTC is 18:00 ET, after-hours.
    assert classify_reaction_session(et(2026, 8, 17, 22, 0)) == ReactionSession.AFTER_HOURS


def test_classify_reaction_session_weekend():
    # 2026-08-15 is a Saturday.
    assert classify_reaction_session(et(2026, 8, 15, 14, 30)) == ReactionSession.WEEKEND_NON_TRADING


def test_reaction_measures_horizons_from_real_candles():
    event = _event(SPY_1H[100].timestamp)
    reaction = measure_market_reaction(event, "SPY", "1h", SPY_1H)
    assert reaction.base_price == SPY_1H[100].close
    assert reaction.evaluation_quality.fully_evaluated is True
    assert all(h.available for h in reaction.price_horizons)


def test_reaction_with_no_candle_history_before_event_is_explicitly_unavailable():
    event = _event(et(2000, 1, 1))  # long before any fixture candle
    reaction = measure_market_reaction(event, "SPY", "1h", SPY_1H)
    assert reaction.base_price is None
    assert reaction.price_horizons == []
    assert reaction.evaluation_quality.fully_evaluated is False
    assert reaction.evaluation_quality.warnings


def test_reaction_insufficient_horizon_near_end_of_history():
    event = _event(SPY_1H[-3].timestamp)
    reaction = measure_market_reaction(event, "SPY", "1h", SPY_1H)
    assert reaction.evaluation_quality.fully_evaluated is False
    assert reaction.evaluation_quality.bars_available_after_detection < 20
    # short horizons still resolve even though the longest ones can't
    assert reaction.price_horizons[0].available is True


def test_reaction_with_empty_candle_list():
    event = _event(et(2026, 8, 20))
    reaction = measure_market_reaction(event, "SPY", "1h", [])
    assert reaction.base_price is None
    assert reaction.evaluation_quality.fully_evaluated is False


def test_reaction_direction_neutral_convention_matches_raw_return():
    """reaction.py always measures in the BULLISH convention -- directional
    and raw returns must be identical since nothing is direction-flipped."""
    event = _event(SPY_1H[100].timestamp)
    reaction = measure_market_reaction(event, "SPY", "1h", SPY_1H)
    for horizon in reaction.price_horizons:
        if horizon.available:
            assert horizon.directional_return_percent == horizon.raw_return_percent


def test_reaction_computed_at_is_set():
    event = _event(SPY_1H[100].timestamp)
    reaction = measure_market_reaction(event, "SPY", "1h", SPY_1H)
    assert reaction.computed_at is not None
