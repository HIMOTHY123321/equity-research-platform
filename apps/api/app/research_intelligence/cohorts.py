"""Generic deterministic cohort/grouping engine (#7). Cohort membership may
ONLY use information frozen at detection time (`entry.detection`, Phase 6's
frozen `SetupCandidate` payload) -- never `entry.latest` and never anything
about a setup's outcome. This is the same detection/evaluation boundary
ADR 0008 already enforces for the ledger itself; cohorts must not quietly
reopen it.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from app.news.config import DEFAULT_CATALYST_CONFIG
from app.news.schemas import SetupCatalystContext
from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.schemas import Partition


class CohortDimension(str, Enum):
    SETUP_TYPE = "setup_type"
    DIRECTION = "direction"
    SYMBOL = "symbol"
    TIMEFRAME = "timeframe"
    DAILY_STRUCTURE = "daily_structure"
    FOUR_HOUR_STRUCTURE = "four_hour_structure"
    ONE_HOUR_STRUCTURE = "one_hour_structure"
    RVOL_BUCKET = "rvol_bucket"
    GAP_STATE = "gap_state"
    RESISTANCE_CONFLUENCE = "resistance_confluence"
    SUPPORT_CONFLUENCE = "support_confluence"
    QUALIFICATION_STATUS = "qualification_status"
    REJECTION_REASON = "rejection_reason"
    PARTITION = "partition"

    # Phase 10 (#H) -- populated only when the caller supplies a
    # `catalyst_context_by_setup_id` map (app.news.setup_linking's output,
    # keyed by setup_id); `None` for every entry otherwise, same "absent
    # dimension data is a plain missing value, never a fabricated bucket"
    # convention every other dimension below already follows.
    CATALYST_CATEGORY = "catalyst_category"
    TIME_SINCE_CATALYST_BUCKET = "time_since_catalyst_bucket"
    CATALYST_RVOL_ELEVATED = "catalyst_rvol_elevated"


# A CohortKey is a tuple of (dimension.value, value-as-string) pairs, in the
# same order the caller requested dimensions in -- hashable, stable, and
# directly inspectable (no opaque hash standing in for what it groups by).
CohortKey = tuple


def _primary_rejection_reason(entry: SetupLedgerEntry) -> Optional[str]:
    """The code of the first failed hard check on the frozen detection
    payload (#16). When several hard checks fail simultaneously, only the
    first (in the detector's own check order) is used as the primary
    reason -- a real simplification, not a hidden one; a rejected candidate
    still carries every failed check on `detection.hard_checks` for anyone
    who needs the full picture."""
    if entry.detection.current_state != "rejected":
        return None
    failed = [c for c in entry.detection.hard_checks if not c.passed]
    return failed[0].code if failed else None


def time_since_catalyst_bucket(hours_before_setup: Optional[float]) -> Optional[str]:
    """Deterministic, fixed buckets (#H) -- a catalyst that occurred AFTER
    the setup (hours_before_setup is None, i.e. only hours_after_setup is
    set) has no "time since" value and returns None here, same as "no
    catalyst at all"; app.news.setup_linking's own before/after lists are
    still the authoritative source for that distinction."""
    if hours_before_setup is None:
        return None
    if hours_before_setup <= 6:
        return "0-6h"
    if hours_before_setup <= 24:
        return "6-24h"
    if hours_before_setup <= 72:
        return "1-3d"
    return ">3d"


def cohort_dimension_value(
    entry: SetupLedgerEntry,
    dimension: CohortDimension,
    partition: Optional[Partition] = None,
    catalyst_context: Optional[SetupCatalystContext] = None,
) -> Optional[str]:
    detection = entry.detection
    fp = detection.fingerprint

    if dimension == CohortDimension.SETUP_TYPE:
        return detection.setup_type.value
    if dimension == CohortDimension.DIRECTION:
        return detection.direction.value
    if dimension == CohortDimension.SYMBOL:
        return detection.symbol
    if dimension == CohortDimension.TIMEFRAME:
        return detection.timeframe.value
    if dimension == CohortDimension.QUALIFICATION_STATUS:
        return detection.current_state.value
    if dimension == CohortDimension.REJECTION_REASON:
        return _primary_rejection_reason(entry)
    if dimension == CohortDimension.PARTITION:
        return partition.value if partition else None

    if dimension == CohortDimension.CATALYST_CATEGORY:
        if catalyst_context is None or catalyst_context.nearest_catalyst is None:
            return None
        return catalyst_context.nearest_catalyst.category.value
    if dimension == CohortDimension.TIME_SINCE_CATALYST_BUCKET:
        if catalyst_context is None or catalyst_context.nearest_catalyst is None:
            return None
        return time_since_catalyst_bucket(catalyst_context.nearest_catalyst.hours_before_setup)
    if dimension == CohortDimension.CATALYST_RVOL_ELEVATED:
        if catalyst_context is None or catalyst_context.nearest_reaction is None:
            return None
        rvol = catalyst_context.nearest_reaction.rvol_at_event
        if rvol is None:
            return None
        return str(rvol >= DEFAULT_CATALYST_CONFIG.reaction_rvol_elevated_threshold)

    if fp is None:
        return None
    if dimension == CohortDimension.DAILY_STRUCTURE:
        return fp.daily_structure.value if fp.daily_structure else None
    if dimension == CohortDimension.FOUR_HOUR_STRUCTURE:
        return fp.four_hour_structure.value if fp.four_hour_structure else None
    if dimension == CohortDimension.ONE_HOUR_STRUCTURE:
        return fp.one_hour_structure.value if fp.one_hour_structure else None
    if dimension == CohortDimension.RVOL_BUCKET:
        return fp.rvol_bucket
    if dimension == CohortDimension.GAP_STATE:
        return fp.gap_state
    if dimension == CohortDimension.RESISTANCE_CONFLUENCE:
        return str(fp.resistance_confluence)
    if dimension == CohortDimension.SUPPORT_CONFLUENCE:
        return str(fp.support_confluence)

    raise ValueError(f"unhandled cohort dimension {dimension!r}")


def cohort_key(
    entry: SetupLedgerEntry,
    dimensions: list[CohortDimension],
    partition: Optional[Partition] = None,
    catalyst_context: Optional[SetupCatalystContext] = None,
) -> CohortKey:
    return tuple(
        (d.value, cohort_dimension_value(entry, d, partition, catalyst_context)) for d in dimensions
    )


def group_by_cohort(
    entries: list[SetupLedgerEntry],
    dimensions: list[CohortDimension],
    partition_by_setup_id: Optional[dict[str, Partition]] = None,
    catalyst_context_by_setup_id: Optional[dict[str, SetupCatalystContext]] = None,
) -> dict[CohortKey, list[SetupLedgerEntry]]:
    """Groups ledger entries into cohorts on the requested dimensions only.
    `partition_by_setup_id` is required if `Partition` is one of the
    requested dimensions -- a caller-supplied mapping (from
    `app.research_intelligence.partitions`) rather than something this
    function infers on its own, since partition assignment is a property of
    the underlying candle series, not of any individual setup.
    `catalyst_context_by_setup_id` (Phase 10, same pattern) is required if
    any CATALYST_* dimension is requested -- a caller-supplied mapping from
    `app.news.setup_linking.build_setup_catalyst_context`, since news data is
    entirely outside this package."""
    partition_by_setup_id = partition_by_setup_id or {}
    catalyst_context_by_setup_id = catalyst_context_by_setup_id or {}
    groups: dict[CohortKey, list[SetupLedgerEntry]] = {}
    for entry in entries:
        partition = partition_by_setup_id.get(entry.setup_id)
        catalyst_context = catalyst_context_by_setup_id.get(entry.setup_id)
        key = cohort_key(entry, dimensions, partition, catalyst_context)
        groups.setdefault(key, []).append(entry)
    return groups
