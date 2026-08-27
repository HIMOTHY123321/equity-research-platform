"""Setup ledger construction (#5, #6, #29). Converts SetupCandidate
snapshots observed during replay into append-only ledger entries: the
`detection` field is written exactly once, at first observation, and never
touched again -- everything replay learns on later bars about the same
setup id updates only the separate `latest`/`current_state` fields.
"""

from __future__ import annotations

from datetime import datetime

from app.research.schemas import SetupLedgerEntry
from app.setup_detection.schemas import SetupCandidate


def new_ledger_entry(
    research_run_id: str, candidate: SetupCandidate, observed_at: datetime
) -> SetupLedgerEntry:
    return SetupLedgerEntry(
        research_run_id=research_run_id,
        setup_id=candidate.id,
        symbol=candidate.symbol,
        timeframe=candidate.timeframe.value,
        setup_type=candidate.setup_type.value,
        direction=candidate.direction.value,
        first_seen_at=observed_at,
        candidate_candle_timestamp=candidate.candidate_candle_timestamp,
        detection=candidate,
        current_state=candidate.current_state.value,
        last_observed_at=observed_at,
        latest=candidate,
    )


def with_updated_lifecycle(
    entry: SetupLedgerEntry, candidate: SetupCandidate, observed_at: datetime
) -> SetupLedgerEntry:
    """Never overwrites `entry.detection` -- only the mutable lifecycle
    view. `model_copy` on a frozen pydantic model still returns a new,
    independently-frozen instance; the original `entry` (and its
    `detection` payload) is untouched."""
    return entry.model_copy(
        update={
            "current_state": candidate.current_state.value,
            "last_observed_at": observed_at,
            "latest": candidate,
        }
    )
