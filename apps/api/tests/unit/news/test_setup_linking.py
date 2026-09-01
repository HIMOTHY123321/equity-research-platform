from datetime import timedelta

from app.market_structure.schemas import Direction
from app.news.config import DEFAULT_CATALYST_CONFIG
from app.news.schemas import (
    CatalystCategory,
    CatalystEvent,
    MarketReaction,
    ReactionSession,
    SetupCatalystContextLabel,
)
from app.news.setup_linking import build_setup_catalyst_context
from app.research.schemas import EvaluationQuality, HorizonOutcome
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupCandidate, SetupLifecycleState
from tests.unit.news.conftest import et

DETECTION_TIME = et(2026, 8, 20, 12, 0)


def _candidate(direction=Direction.BULLISH):
    return SetupCandidate(
        id="test-setup-1",
        symbol="ACME",
        timeframe=Timeframe.ONE_HOUR,
        setup_type="breakout_retest",
        direction=direction,
        candidate_candle_timestamp=DETECTION_TIME,
        created_at=DETECTION_TIME,
        current_state=SetupLifecycleState.QUALIFIED,
        transitions=[],
        hard_checks=[],
        soft_checks=[],
        conflicts=[],
    )


def _event(event_id, timestamp, category=CatalystCategory.EARNINGS):
    return CatalystEvent(
        event_id=event_id,
        primary_timestamp=timestamp,
        category=category,
        affected_symbols=("ACME",),
        contributing_article_ids=["a1"],
        source_count=1,
        earliest_published_at=timestamp,
        latest_update_at=timestamp,
        title="test event",
    )


def _reaction(event_id, initial_pct, last_pct, initial_bars=1, last_bars=5):
    horizons = [
        HorizonOutcome(
            horizon_bars=initial_bars,
            available=True,
            future_close=100 + initial_pct,
            absolute_change=initial_pct,
            raw_return_percent=initial_pct,
            directional_return_percent=initial_pct,
        )
    ]
    if last_pct is not None:
        horizons.append(
            HorizonOutcome(
                horizon_bars=last_bars,
                available=True,
                future_close=100 + last_pct,
                absolute_change=last_pct,
                raw_return_percent=last_pct,
                directional_return_percent=last_pct,
            )
        )
    return MarketReaction(
        event_id=event_id,
        symbol="ACME",
        timeframe="1h",
        session_at_event=ReactionSession.REGULAR,
        base_price=100.0,
        price_horizons=horizons,
        evaluation_quality=EvaluationQuality(bars_available_after_detection=20, fully_evaluated=True),
        computed_at=DETECTION_TIME,
    )


def test_no_recent_catalyst_when_no_events_in_window():
    context = build_setup_catalyst_context(_candidate(), [], {})
    assert context.label == SetupCatalystContextLabel.NO_RECENT_CATALYST
    assert context.nearest_catalyst is None


def test_no_recent_catalyst_when_event_outside_window():
    far_event = _event("evt1", DETECTION_TIME - timedelta(hours=200))
    context = build_setup_catalyst_context(_candidate(), [far_event], {})
    assert context.label == SetupCatalystContextLabel.NO_RECENT_CATALYST


def test_timing_ambiguous_when_catalyst_within_ambiguous_window():
    close_event = _event("evt1", DETECTION_TIME - timedelta(minutes=10))
    context = build_setup_catalyst_context(_candidate(), [close_event], {})
    assert context.label == SetupCatalystContextLabel.CATALYST_TIMING_AMBIGUOUS
    assert "close" in context.label_basis.lower() or "minutes" in context.label_basis.lower()


def test_timing_ambiguous_when_no_reaction_data_available():
    event = _event("evt1", DETECTION_TIME - timedelta(hours=2))
    context = build_setup_catalyst_context(_candidate(), [event], {})  # no reaction in dict
    assert context.label == SetupCatalystContextLabel.CATALYST_TIMING_AMBIGUOUS
    assert "reaction evidence" in context.label_basis.lower()


def test_catalyst_conflicted_when_reaction_opposes_setup_direction():
    event = _event("evt1", DETECTION_TIME - timedelta(hours=2))
    reaction = _reaction("evt1", initial_pct=-0.5, last_pct=None)
    context = build_setup_catalyst_context(_candidate(Direction.BULLISH), [event], {"evt1": reaction})
    assert context.label == SetupCatalystContextLabel.CATALYST_CONFLICTED


def test_catalyst_supported_persistence_inconclusive():
    event = _event("evt1", DETECTION_TIME - timedelta(hours=2))
    reaction = _reaction("evt1", initial_pct=0.5, last_pct=0.35)  # ratio 0.7, between fade/persist
    context = build_setup_catalyst_context(_candidate(), [event], {"evt1": reaction})
    assert context.label == SetupCatalystContextLabel.CATALYST_SUPPORTED


def test_catalyst_reaction_faded():
    event = _event("evt1", DETECTION_TIME - timedelta(hours=2))
    reaction = _reaction("evt1", initial_pct=0.5, last_pct=0.2)  # ratio 0.4 <= 0.5
    context = build_setup_catalyst_context(_candidate(), [event], {"evt1": reaction})
    assert context.label == SetupCatalystContextLabel.CATALYST_REACTION_FADED


def test_catalyst_reaction_persisted():
    event = _event("evt1", DETECTION_TIME - timedelta(hours=2))
    reaction = _reaction("evt1", initial_pct=0.5, last_pct=0.45)  # ratio 0.9 >= 0.8
    context = build_setup_catalyst_context(_candidate(), [event], {"evt1": reaction})
    assert context.label == SetupCatalystContextLabel.CATALYST_REACTION_PERSISTED


def test_timing_ambiguous_when_reaction_magnitude_too_small():
    event = _event("evt1", DETECTION_TIME - timedelta(hours=2))
    reaction = _reaction("evt1", initial_pct=0.05, last_pct=None)  # between -0.15 and 0.15
    context = build_setup_catalyst_context(_candidate(), [event], {"evt1": reaction})
    assert context.label == SetupCatalystContextLabel.CATALYST_TIMING_AMBIGUOUS
    assert "too small" in context.label_basis.lower()


def test_reaction_realigned_for_bearish_setup():
    """A negative raw reaction agrees with a BEARISH setup's own direction
    -- must classify as supported, not conflicted."""
    event = _event("evt1", DETECTION_TIME - timedelta(hours=2))
    reaction = _reaction("evt1", initial_pct=-0.5, last_pct=-0.45)
    context = build_setup_catalyst_context(_candidate(Direction.BEARISH), [event], {"evt1": reaction})
    assert context.label == SetupCatalystContextLabel.CATALYST_REACTION_PERSISTED


def test_catalysts_before_and_after_split_correctly():
    before_event = _event("evt-before", DETECTION_TIME - timedelta(hours=5))
    after_event = _event("evt-after", DETECTION_TIME + timedelta(hours=5), category=CatalystCategory.GUIDANCE)
    context = build_setup_catalyst_context(_candidate(), [before_event, after_event], {})
    assert len(context.catalysts_before) == 1
    assert len(context.catalysts_after) == 1
    assert context.catalysts_before[0].event_id == "evt-before"
    assert context.catalysts_after[0].event_id == "evt-after"


def test_label_basis_is_always_a_nonempty_string():
    context = build_setup_catalyst_context(_candidate(), [], {})
    assert isinstance(context.label_basis, str)
    assert len(context.label_basis) > 0


def test_default_config_thresholds_used_when_not_overridden():
    assert DEFAULT_CATALYST_CONFIG.timing_ambiguous_window_minutes == 30.0
