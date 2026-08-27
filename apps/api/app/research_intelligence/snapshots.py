"""Research snapshot persistence (#34) and run comparison (#35). Same
ABC + SqlAlchemy-implementation pattern as `app.research.repository` --
callers depend only on `SnapshotRepository`, never on SQLAlchemy directly.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Base, ResearchSnapshotRecord
from app.research_intelligence.schemas import ResearchSnapshot, SnapshotComparison, SnapshotFieldDiff


class SnapshotNotFoundError(LookupError):
    def __init__(self, snapshot_id: str) -> None:
        super().__init__(f"Research snapshot {snapshot_id!r} not found")
        self.snapshot_id = snapshot_id


class SnapshotRepository(ABC):
    @abstractmethod
    def create_snapshot(
        self,
        *,
        label: str,
        research_run_ids: list[str],
        config_hash: str,
        dataset_manifest: dict,
        cohort_definition: dict,
        filters: dict,
        statistical_output: dict,
        warning_flags: list[str],
    ) -> str: ...

    @abstractmethod
    def get_snapshot(self, snapshot_id: str) -> Optional[ResearchSnapshot]: ...

    @abstractmethod
    def list_snapshots(self, *, limit: int = 50) -> list[ResearchSnapshot]: ...


class SqlAlchemySnapshotRepository(SnapshotRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        # Same SQLite local-dev bootstrap convention as
        # SqlAlchemyResearchRepository (docs/decisions/0008) -- a no-op
        # against an already-provisioned Postgres database.
        Base.metadata.create_all(
            bind=session.get_bind(), tables=[ResearchSnapshotRecord.__table__], checkfirst=True
        )

    def create_snapshot(
        self,
        *,
        label,
        research_run_ids,
        config_hash,
        dataset_manifest,
        cohort_definition,
        filters,
        statistical_output,
        warning_flags,
    ) -> str:
        row = ResearchSnapshotRecord(
            label=label,
            research_run_ids=research_run_ids,
            config_hash=config_hash,
            dataset_manifest=dataset_manifest,
            cohort_definition=cohort_definition,
            filters=filters,
            statistical_output=statistical_output,
            warning_flags=warning_flags,
        )
        self._session.add(row)
        self._session.commit()
        return str(row.id)

    def get_snapshot(self, snapshot_id: str) -> Optional[ResearchSnapshot]:
        try:
            row = self._session.get(ResearchSnapshotRecord, uuid.UUID(snapshot_id))
        except ValueError:
            return None
        return self._to_pydantic(row) if row else None

    def list_snapshots(self, *, limit: int = 50) -> list[ResearchSnapshot]:
        rows = self._session.execute(
            select(ResearchSnapshotRecord).order_by(ResearchSnapshotRecord.created_at.desc()).limit(limit)
        ).scalars()
        return [self._to_pydantic(row) for row in rows]

    def _to_pydantic(self, row: ResearchSnapshotRecord) -> ResearchSnapshot:
        return ResearchSnapshot(
            snapshot_id=str(row.id),
            label=row.label,
            research_run_ids=row.research_run_ids,
            config_hash=row.config_hash,
            dataset_manifest=row.dataset_manifest,
            cohort_definition=row.cohort_definition,
            filters=row.filters,
            statistical_output=row.statistical_output,
            warning_flags=row.warning_flags,
            created_at=row.created_at.replace(tzinfo=timezone.utc)
            if row.created_at.tzinfo is None
            else row.created_at,
        )


def compare_detector_versions(a: ResearchSnapshot, b: ResearchSnapshot) -> SnapshotComparison:
    """(Phase 9 #17) A named entry point for the specific comparison this
    package must make easy: "did a different set of detector rules produce
    a different result on the same data?" This is not a new mechanism --
    `config_hash` (`app.research.config_hash.compute_config_hash`) already
    hashes every threshold in `FeatureConfig`/`MarketStructureConfig`/
    `SupportResistanceConfig`/`SetupDetectionConfig`/`ResearchConfig`, so it
    already *is* a detector-version fingerprint, and `compare_snapshots`
    already reports `same_config_hash` alongside `same_dataset`. This
    wrapper exists purely so "compare detector versions" has one obvious,
    discoverable name instead of requiring a caller to know that fact.
    Infrastructure only (#17): nothing here generates a second detector
    version -- that stays a manual, deliberate act (a config change,
    committed and run separately), never automatic.
    """
    return compare_snapshots(a, b)


def compare_snapshots(a: ResearchSnapshot, b: ResearchSnapshot) -> SnapshotComparison:
    """(#35) Never silently merges -- every field that differs is listed
    explicitly, and config/dataset identity is surfaced up front so a
    caller can immediately tell whether this is "same rules, different
    period" or "same period, different rules" (or neither)."""
    diffs: list[SnapshotFieldDiff] = []

    def add_diff(field: str, value_a, value_b):
        changed = value_a != value_b
        diffs.append(
            SnapshotFieldDiff(
                field=field,
                snapshot_a_value=str(value_a) if value_a is not None else None,
                snapshot_b_value=str(value_b) if value_b is not None else None,
                changed=changed,
            )
        )

    manifest_a, manifest_b = a.dataset_manifest, b.dataset_manifest
    symbols_a, symbols_b = manifest_a.get("symbols"), manifest_b.get("symbols")
    timeframe_a, timeframe_b = manifest_a.get("timeframe"), manifest_b.get("timeframe")
    start_a, start_b = manifest_a.get("requested_start"), manifest_b.get("requested_start")
    end_a, end_b = manifest_a.get("requested_end"), manifest_b.get("requested_end")

    add_diff("config_hash", a.config_hash, b.config_hash)
    add_diff("dataset_symbols", symbols_a, symbols_b)
    add_diff("dataset_timeframe", timeframe_a, timeframe_b)
    add_diff("dataset_requested_start", start_a, start_b)
    add_diff("dataset_requested_end", end_a, end_b)
    add_diff("cohort_definition", a.cohort_definition, b.cohort_definition)
    add_diff("filters", a.filters, b.filters)

    same_dataset = (
        symbols_a == symbols_b and timeframe_a == timeframe_b and start_a == start_b and end_a == end_b
    )
    return SnapshotComparison(
        snapshot_a_id=a.snapshot_id,
        snapshot_b_id=b.snapshot_id,
        same_config_hash=a.config_hash == b.config_hash,
        same_dataset=same_dataset,
        field_diffs=diffs,
    )
