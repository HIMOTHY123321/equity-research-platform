from app.news.schemas import (
    CatalystCategory,
    CatalystReference,
    MarketReaction,
    ReactionSession,
    SetupCatalystContext,
    SetupCatalystContextLabel,
)
from app.research.replay import run_replay
from app.research_intelligence.cohorts import (
    CohortDimension,
    cohort_dimension_value,
    group_by_cohort,
    time_since_catalyst_bucket,
)
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _real_ledger_entries():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "catalyst-cohort-test-run"
    )
    return result.ledger_entries


def _context(category=None, hours_before=None, rvol=None):
    nearest = None
    if category is not None:
        nearest = CatalystReference(
            event_id="evt1", category=category, primary_timestamp=SPY_1H[0].timestamp, source_count=1,
            hours_before_setup=hours_before,
        )
    reaction = None
    if rvol is not None:
        reaction = MarketReaction(
            event_id="evt1", symbol=SYMBOL, timeframe="1h", session_at_event=ReactionSession.REGULAR,
            rvol_at_event=rvol, computed_at=SPY_1H[0].timestamp,
        )
    label = (
        SetupCatalystContextLabel.NO_RECENT_CATALYST
        if nearest is None
        else SetupCatalystContextLabel.CATALYST_SUPPORTED
    )
    return SetupCatalystContext(
        setup_id="unused",
        symbol=SYMBOL,
        nearest_catalyst=nearest,
        nearest_reaction=reaction,
        label=label,
        label_basis="test",
    )


def test_time_since_catalyst_bucket_thresholds():
    assert time_since_catalyst_bucket(None) is None
    assert time_since_catalyst_bucket(3) == "0-6h"
    assert time_since_catalyst_bucket(6) == "0-6h"
    assert time_since_catalyst_bucket(6.01) == "6-24h"
    assert time_since_catalyst_bucket(24) == "6-24h"
    assert time_since_catalyst_bucket(48) == "1-3d"
    assert time_since_catalyst_bucket(72) == "1-3d"
    assert time_since_catalyst_bucket(72.01) == ">3d"


def test_catalyst_dimensions_are_none_without_context_supplied():
    entries = _real_ledger_entries()
    entry = entries[0]
    assert cohort_dimension_value(entry, CohortDimension.CATALYST_CATEGORY) is None
    assert cohort_dimension_value(entry, CohortDimension.TIME_SINCE_CATALYST_BUCKET) is None
    assert cohort_dimension_value(entry, CohortDimension.CATALYST_RVOL_ELEVATED) is None


def test_catalyst_category_dimension_reads_nearest_catalyst():
    entries = _real_ledger_entries()
    entry = entries[0]
    context = _context(category=CatalystCategory.EARNINGS, hours_before=2)
    value = cohort_dimension_value(entry, CohortDimension.CATALYST_CATEGORY, catalyst_context=context)
    assert value == "earnings"


def test_catalyst_rvol_elevated_dimension_uses_configured_threshold():
    entries = _real_ledger_entries()
    entry = entries[0]
    high = _context(category=CatalystCategory.EARNINGS, hours_before=1, rvol=3.0)
    low = _context(category=CatalystCategory.EARNINGS, hours_before=1, rvol=0.5)
    dim = CohortDimension.CATALYST_RVOL_ELEVATED
    assert cohort_dimension_value(entry, dim, catalyst_context=high) == "True"
    assert cohort_dimension_value(entry, dim, catalyst_context=low) == "False"


def test_group_by_cohort_with_catalyst_context_map():
    entries = _real_ledger_entries()[:4]
    context_by_setup_id = {
        entries[0].setup_id: _context(category=CatalystCategory.EARNINGS, hours_before=2),
        entries[1].setup_id: _context(category=CatalystCategory.GUIDANCE, hours_before=2),
        # entries[2], entries[3] deliberately absent -- no catalyst context known
    }
    groups = group_by_cohort(
        entries, [CohortDimension.CATALYST_CATEGORY], catalyst_context_by_setup_id=context_by_setup_id
    )
    total = sum(len(members) for members in groups.values())
    assert total == len(entries)
    assert (("catalyst_category", "earnings"),) in groups
    assert (("catalyst_category", "guidance"),) in groups
    assert (("catalyst_category", None),) in groups


def test_group_by_cohort_backward_compatible_without_catalyst_param():
    """Existing callers that never pass catalyst_context_by_setup_id must
    see byte-identical behavior to before Phase 10."""
    entries = _real_ledger_entries()
    groups_old_style = group_by_cohort(entries, [CohortDimension.SETUP_TYPE])
    groups_explicit_none = group_by_cohort(
        entries, [CohortDimension.SETUP_TYPE], catalyst_context_by_setup_id=None
    )
    assert set(groups_old_style.keys()) == set(groups_explicit_none.keys())
