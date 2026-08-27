from app.research.replay import run_replay
from app.research_intelligence.cohorts import CohortDimension, cohort_dimension_value, group_by_cohort
from app.research_intelligence.schemas import Partition
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _real_ledger_entries():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "cohort-test-run")
    return result.ledger_entries


def test_grouping_by_setup_type_and_direction_accounts_for_every_entry():
    entries = _real_ledger_entries()
    groups = group_by_cohort(entries, [CohortDimension.SETUP_TYPE, CohortDimension.DIRECTION])
    total_grouped = sum(len(members) for members in groups.values())
    assert total_grouped == len(entries)
    # Every member of a cohort really does share that cohort's key values.
    for key, members in groups.items():
        setup_type_value = dict(key)["setup_type"]
        direction_value = dict(key)["direction"]
        for entry in members:
            assert entry.detection.setup_type.value == setup_type_value
            assert entry.detection.direction.value == direction_value


def test_rejected_trend_pullback_groups_by_its_actual_failed_hard_check_code():
    entries = _real_ledger_entries()
    rejected_pullbacks = [
        e for e in entries if e.setup_type == "trend_pullback" and e.detection.current_state == "rejected"
    ]
    assert rejected_pullbacks, "expected at least one rejected trend_pullback in the real SPY fixture"
    for entry in rejected_pullbacks:
        reason = cohort_dimension_value(entry, CohortDimension.REJECTION_REASON)
        failed_codes = {c.code for c in entry.detection.hard_checks if not c.passed}
        assert reason in failed_codes


def test_qualified_entries_have_no_rejection_reason():
    entries = _real_ledger_entries()
    qualified = [e for e in entries if e.detection.current_state == "qualified"]
    assert qualified
    for entry in qualified:
        assert cohort_dimension_value(entry, CohortDimension.REJECTION_REASON) is None


def test_cohort_membership_ignores_the_latest_lifecycle_view_uses_only_detection():
    # Item #7's hard rule: cohort membership may only use info frozen at
    # detection time. Prove it by construction -- swap `latest` for a
    # different candidate on the same entry and confirm the cohort key is
    # unchanged, since only `detection` should ever be consulted.
    entries = _real_ledger_entries()
    entry = next(e for e in entries if e.detection.setup_type.value == "trend_pullback")
    tampered = entry.model_copy(
        update={"latest": entry.detection.model_copy(update={"direction": "bearish"})}
    )

    original_key = tuple(
        cohort_dimension_value(entry, d)
        for d in (CohortDimension.SETUP_TYPE, CohortDimension.DIRECTION, CohortDimension.RVOL_BUCKET)
    )
    tampered_key = tuple(
        cohort_dimension_value(tampered, d)
        for d in (CohortDimension.SETUP_TYPE, CohortDimension.DIRECTION, CohortDimension.RVOL_BUCKET)
    )
    assert original_key == tampered_key


def test_partition_dimension_requires_an_explicit_mapping_never_inferred():
    entries = _real_ledger_entries()
    entry = entries[0]
    assert cohort_dimension_value(entry, CohortDimension.PARTITION, partition=None) is None
    assert cohort_dimension_value(entry, CohortDimension.PARTITION, partition=Partition.TEST) == "test"


def test_group_by_cohort_applies_the_supplied_partition_mapping():
    entries = _real_ledger_entries()[:3]
    mapping = {entries[0].setup_id: Partition.DEVELOPMENT, entries[1].setup_id: Partition.TEST}
    groups = group_by_cohort(entries, [CohortDimension.PARTITION], partition_by_setup_id=mapping)
    dev_group = groups[(("partition", "development"),)]
    assert entries[0] in dev_group
