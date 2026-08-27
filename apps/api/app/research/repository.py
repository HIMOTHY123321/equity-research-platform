"""Persistence abstraction (#27-#30, #50). Same ABC + concrete-implementation
pattern as app.watchlist.repository -- callers depend only on
`ResearchRepository`, never on SQLAlchemy directly, so the storage backend
can change without touching the engine/API layer.

`SqlAlchemyResearchRepository` is the only implementation; it works against
whatever `DATABASE_URL` resolves to (SQLite by default -- see app/config.py
-- or Postgres). See docs/decisions/0008 for why the Phase 7 tables are new
rather than built on the Phase 1 schema, and for the SQLite bootstrap this
module performs on first use rather than relying on the (Postgres-only)
0001 migration having been run.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Base, ResearchRun, SetupOutcomeRecord
from app.database.models import SetupLedgerEntry as SetupLedgerEntryRow
from app.research.schemas import (
    DatasetProvenance,
    ResearchRunSummary,
    SetupLedgerEntry,
    SetupOutcome,
)
from app.setup_detection.schemas import SetupCandidate


class ResearchRunNotFoundError(LookupError):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"Research run {run_id!r} not found")
        self.run_id = run_id


class ResearchRunRecord:
    def __init__(self, row: ResearchRun) -> None:
        self.id = str(row.id)
        self.symbol = row.symbol
        self.timeframe = row.timeframe
        self.start_date = row.start_date
        self.end_date = row.end_date
        self.status = row.status
        self.config_hash = row.config_hash
        self.config_snapshot = row.config_snapshot
        self.dataset_provenance = DatasetProvenance.model_validate(row.dataset_provenance)
        self.bars_processed = row.bars_processed
        self.qualified_count = row.qualified_count
        self.rejected_count = row.rejected_count
        self.runtime_seconds = row.runtime_seconds
        self.error = row.error
        self.created_at = row.created_at
        self.completed_at = row.completed_at


class ResearchRepository(ABC):
    @abstractmethod
    def create_run(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        config_hash: str,
        config_snapshot: dict,
        dataset_provenance: DatasetProvenance,
    ) -> str: ...

    @abstractmethod
    def store_completed_run(
        self,
        run_id: str,
        *,
        ledger_entries: list[SetupLedgerEntry],
        bars_processed: int,
        qualified_count: int,
        rejected_count: int,
        runtime_seconds: float,
        summary: ResearchRunSummary,
    ) -> None: ...

    @abstractmethod
    def fail_run(self, run_id: str, error: str) -> None: ...

    @abstractmethod
    def get_run(self, run_id: str) -> Optional[ResearchRunRecord]: ...

    @abstractmethod
    def list_runs(self, *, limit: int = 50) -> list[ResearchRunRecord]: ...

    @abstractmethod
    def list_ledger_entries(
        self,
        run_id: str,
        *,
        setup_type: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[SetupLedgerEntry]: ...

    @abstractmethod
    def get_summary(self, run_id: str) -> Optional[ResearchRunSummary]: ...


class SqlAlchemyResearchRepository(ResearchRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        # SQLite local-dev bootstrap (#27): creates only the Phase 7 tables
        # directly, rather than requiring the Postgres-only 0001 migration
        # to have been run first. A no-op against an already-provisioned
        # Postgres database (checkfirst=True skips tables that exist).
        bind = session.get_bind()
        Base.metadata.create_all(
            bind=bind,
            tables=[ResearchRun.__table__, SetupLedgerEntryRow.__table__, SetupOutcomeRecord.__table__],
            checkfirst=True,
        )

    def create_run(
        self,
        *,
        symbol,
        timeframe,
        start_date,
        end_date,
        config_hash,
        config_snapshot,
        dataset_provenance,
    ) -> str:
        row = ResearchRun(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            status="running",
            config_hash=config_hash,
            config_snapshot=config_snapshot,
            dataset_provenance=dataset_provenance.model_dump(mode="json"),
        )
        self._session.add(row)
        self._session.commit()
        return str(row.id)

    def store_completed_run(
        self,
        run_id,
        *,
        ledger_entries,
        bars_processed,
        qualified_count,
        rejected_count,
        runtime_seconds,
        summary,
    ) -> None:
        run_uuid = uuid.UUID(run_id)
        run_row = self._session.get(ResearchRun, run_uuid)
        if run_row is None:
            raise ResearchRunNotFoundError(run_id)

        for entry in ledger_entries:
            entry_row = SetupLedgerEntryRow(
                research_run_id=run_uuid,
                setup_id=entry.setup_id,
                symbol=entry.symbol,
                timeframe=entry.timeframe,
                setup_type=entry.setup_type,
                direction=entry.direction,
                first_seen_at=entry.first_seen_at,
                candidate_candle_timestamp=entry.candidate_candle_timestamp,
                detection_snapshot=entry.detection.model_dump(mode="json"),
                current_state=entry.current_state,
                last_observed_at=entry.last_observed_at,
                latest_snapshot=entry.latest.model_dump(mode="json"),
            )
            self._session.add(entry_row)
            self._session.flush()  # assigns entry_row.id

            if entry.outcome is not None:
                self._session.add(
                    SetupOutcomeRecord(
                        ledger_entry_id=entry_row.id,
                        outcome=entry.outcome.model_dump(mode="json"),
                    )
                )

        run_row.status = "completed"
        run_row.bars_processed = bars_processed
        run_row.qualified_count = qualified_count
        run_row.rejected_count = rejected_count
        run_row.runtime_seconds = runtime_seconds
        run_row.summary = summary.model_dump(mode="json")
        run_row.completed_at = datetime.now(run_row.start_date.tzinfo)
        self._session.commit()

    def fail_run(self, run_id: str, error: str) -> None:
        run_row = self._session.get(ResearchRun, uuid.UUID(run_id))
        if run_row is None:
            raise ResearchRunNotFoundError(run_id)
        run_row.status = "failed"
        run_row.error = error[:2000]
        run_row.completed_at = datetime.now(run_row.start_date.tzinfo)
        self._session.commit()

    def get_run(self, run_id: str) -> Optional[ResearchRunRecord]:
        try:
            row = self._session.get(ResearchRun, uuid.UUID(run_id))
        except ValueError:
            return None
        return ResearchRunRecord(row) if row else None

    def list_runs(self, *, limit: int = 50) -> list[ResearchRunRecord]:
        rows = self._session.execute(
            select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(limit)
        ).scalars()
        return [ResearchRunRecord(row) for row in rows]

    def list_ledger_entries(
        self,
        run_id: str,
        *,
        setup_type: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[SetupLedgerEntry]:
        query = select(SetupLedgerEntryRow).where(SetupLedgerEntryRow.research_run_id == uuid.UUID(run_id))
        if setup_type is not None:
            query = query.where(SetupLedgerEntryRow.setup_type == setup_type)
        if state is not None:
            query = query.where(SetupLedgerEntryRow.current_state == state)
        query = query.order_by(SetupLedgerEntryRow.candidate_candle_timestamp).offset(offset).limit(limit)

        rows = self._session.execute(query).scalars().all()
        return [self._to_pydantic(row) for row in rows]

    def get_summary(self, run_id: str) -> Optional[ResearchRunSummary]:
        row = self._session.get(ResearchRun, uuid.UUID(run_id))
        if row is None or row.summary is None:
            return None
        return ResearchRunSummary.model_validate(row.summary)

    def _to_pydantic(self, row: SetupLedgerEntryRow) -> SetupLedgerEntry:
        outcome_row = self._session.execute(
            select(SetupOutcomeRecord).where(SetupOutcomeRecord.ledger_entry_id == row.id)
        ).scalar_one_or_none()

        return SetupLedgerEntry(
            research_run_id=str(row.research_run_id),
            setup_id=row.setup_id,
            symbol=row.symbol,
            timeframe=row.timeframe,
            setup_type=row.setup_type,
            direction=row.direction,
            first_seen_at=row.first_seen_at,
            candidate_candle_timestamp=row.candidate_candle_timestamp,
            detection=SetupCandidate.model_validate(row.detection_snapshot),
            current_state=row.current_state,
            last_observed_at=row.last_observed_at,
            latest=SetupCandidate.model_validate(row.latest_snapshot),
            outcome=SetupOutcome.model_validate(outcome_row.outcome) if outcome_row else None,
        )
