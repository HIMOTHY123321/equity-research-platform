"""Phase 10 (#I) analog engine catalyst-context extension. Verifies: (1)
`catalyst_context=None` (the default) reproduces pre-Phase-10 behavior
exactly, (2) supplying context populates the two new optional dimensions,
(3) missing context on either side is reported as a missing dimension
(contributes nothing), and (4) including catalyst context can materially
change ranking -- while future outcome data is never consulted anywhere in
this path.
"""

from app.market_structure.schemas import Direction
from app.news.schemas import (
    CatalystCategory,
    CatalystReference,
    SetupCatalystContext,
    SetupCatalystContextLabel,
)
from app.research_intelligence.analogs import distance_between, extract_features
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupCandidate, SetupLifecycleState
from tests.unit.news.conftest import et

DETECTION_TIME = et(2026, 8, 20, 12, 0)


def _candidate(setup_id="c1"):
    return SetupCandidate(
        id=setup_id,
        symbol="ACME",
        timeframe=Timeframe.ONE_HOUR,
        setup_type="breakout_retest",
        direction=Direction.BULLISH,
        candidate_candle_timestamp=DETECTION_TIME,
        created_at=DETECTION_TIME,
        current_state=SetupLifecycleState.QUALIFIED,
        transitions=[],
        hard_checks=[],
        soft_checks=[],
        conflicts=[],
    )


def _context(category, hours_before=2.0):
    return SetupCatalystContext(
        setup_id="unused",
        symbol="ACME",
        nearest_catalyst=CatalystReference(
            event_id="evt1", category=category, primary_timestamp=DETECTION_TIME, source_count=1,
            hours_before_setup=hours_before,
        ),
        label=SetupCatalystContextLabel.CATALYST_SUPPORTED,
        label_basis="test",
    )


def test_extract_features_default_none_context_leaves_catalyst_fields_none():
    features = extract_features(_candidate(), detection_close=100.0)
    assert features.catalyst_category is None
    assert features.catalyst_recency_bucket is None


def test_extract_features_populates_catalyst_fields_when_context_supplied():
    context = _context(CatalystCategory.EARNINGS, hours_before=2.0)
    features = extract_features(_candidate(), detection_close=100.0, catalyst_context=context)
    assert features.catalyst_category == "earnings"
    assert features.catalyst_recency_bucket == "0-6h"


def test_extract_features_with_no_nearest_catalyst_stays_none():
    context = SetupCatalystContext(
        setup_id="unused",
        symbol="ACME",
        label=SetupCatalystContextLabel.NO_RECENT_CATALYST,
        label_basis="test",
    )
    features = extract_features(_candidate(), detection_close=100.0, catalyst_context=context)
    assert features.catalyst_category is None
    assert features.catalyst_recency_bucket is None


def test_distance_between_reports_catalyst_dims_as_missing_when_absent_on_both_sides():
    a = extract_features(_candidate("a"), detection_close=100.0)
    b = extract_features(_candidate("b"), detection_close=100.0)
    distance = distance_between(a, b)
    assert "catalyst_category" in distance.missing_dimensions
    assert "catalyst_recency_bucket" in distance.missing_dimensions


def test_distance_between_scores_differing_catalyst_category():
    a = extract_features(
        _candidate("a"), detection_close=100.0, catalyst_context=_context(CatalystCategory.EARNINGS)
    )
    b = extract_features(
        _candidate("b"), detection_close=100.0, catalyst_context=_context(CatalystCategory.GEOPOLITICAL)
    )
    distance = distance_between(a, b)
    assert "catalyst_category" in distance.differing_dimensions
    entry = next(d for d in distance.breakdown if d.dimension == "catalyst_category")
    assert entry.contribution == DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.analog_weights["catalyst_category"]


def test_distance_between_matches_same_catalyst_category():
    a = extract_features(
        _candidate("a"), detection_close=100.0, catalyst_context=_context(CatalystCategory.EARNINGS)
    )
    b = extract_features(
        _candidate("b"), detection_close=100.0, catalyst_context=_context(CatalystCategory.EARNINGS)
    )
    distance = distance_between(a, b)
    assert "catalyst_category" in distance.matched_dimensions


def test_including_catalyst_context_can_change_ranking():
    """Two otherwise-identical candidates: without catalyst context they
    are equidistant from the query; with it, the one sharing the query's
    catalyst category ranks strictly closer."""
    query = extract_features(
        _candidate("query"), detection_close=100.0, catalyst_context=_context(CatalystCategory.EARNINGS)
    )
    same_category = extract_features(
        _candidate("same"), detection_close=100.0, catalyst_context=_context(CatalystCategory.EARNINGS)
    )
    different_category = extract_features(
        _candidate("diff"), detection_close=100.0, catalyst_context=_context(CatalystCategory.GEOPOLITICAL)
    )

    distance_same = distance_between(query, same_category)
    distance_diff = distance_between(query, different_category)
    assert distance_same.distance < distance_diff.distance

    # Without catalyst context, the two candidates are identical to the query
    # on every other dimension -- confirm they'd have tied.
    query_no_ctx = extract_features(_candidate("query"), detection_close=100.0)
    same_no_ctx = extract_features(_candidate("same"), detection_close=100.0)
    diff_no_ctx = extract_features(_candidate("diff"), detection_close=100.0)
    same_distance = distance_between(query_no_ctx, same_no_ctx).distance
    diff_distance = distance_between(query_no_ctx, diff_no_ctx).distance
    assert same_distance == diff_distance


def test_analog_features_schema_carries_no_outcome_data():
    """distance_between/rank_analogs operate purely on AnalogFeatures --
    SetupOutcome/future data is structurally impossible to reach from here
    (#I "future outcome data must NEVER influence analog ranking") because
    the type itself has no field capable of holding it, catalyst dimensions
    included."""
    from app.research_intelligence.schemas import AnalogFeatures

    field_names = set(AnalogFeatures.model_fields.keys())
    assert not any("outcome" in name.lower() or "return" in name.lower() for name in field_names)
