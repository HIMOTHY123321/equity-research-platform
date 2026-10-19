"""Persistence for Long-Term Research snapshots, the scheduled-scan
idempotency guard, and the small amount of per-user push-eligibility
reading this feature needs -- same ABC + SqlAlchemy-implementation
pattern as app.alerts.repository.

Deliberately reads `UserPushPreferenceRecord` directly (the same table
app.alerts.repository already manages) rather than importing that
module's `AlertRepository` -- this avoids coupling the long-term
research domain to the short-term alert domain for what is, here, just
two columns on one shared row (push_enabled's long-term sibling
`long_term_push_enabled`, and the shared encrypted Pushover key).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import (
    Base,
    LongTermResearchSnapshotRecord,
    LongTermScheduledScanRunRecord,
    Symbol,
    UserPushPreferenceRecord,
    Watchlist,
    WatchlistSymbol,
)
from app.long_term_research.schemas import (
    LongTermEvidenceQuality,
    LongTermFactorBundle,
    LongTermResearchResult,
    LongTermResearchState,
)


class LongTermResearchRepository(ABC):
    @abstractmethod
    def insert_snapshot(self, result: LongTermResearchResult) -> None: ...

    @abstractmethod
    def get_latest_snapshot(self, symbol: str) -> Optional[LongTermResearchResult]: ...

    @abstractmethod
    def list_latest_snapshots(self, symbols: list[str]) -> dict[str, LongTermResearchResult]: ...

    @abstractmethod
    def list_user_watchlist_symbols(self, user_id: UUID) -> list[str]: ...

    @abstractmethod
    def list_all_watchlist_symbols_union(self) -> list[str]: ...

    @abstractmethod
    def list_push_eligible_user_ids(self, symbol: str) -> list[UUID]: ...

    @abstractmethod
    def get_long_term_push_enabled(self, user_id: UUID) -> bool: ...

    @abstractmethod
    def set_long_term_push_enabled(self, user_id: UUID, enabled: bool) -> None: ...

    @abstractmethod
    def get_user_pushover_key_encrypted(self, user_id: UUID) -> Optional[str]: ...

    @abstractmethod
    def claim_scheduled_scan_run(self, *, run_date: str, as_of: datetime, symbol_count: int) -> bool:
        """Returns True if this call is the one that got to run the
        scheduled scan for `run_date` (i.e. no row existed yet and this
        call just created it); False if a scheduled scan already ran for
        that date -- the caller must then skip running the scan again."""
        ...


class SqlAlchemyLongTermResearchRepository(LongTermResearchRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        Base.metadata.create_all(
            bind=session.get_bind(),
            tables=[
                LongTermResearchSnapshotRecord.__table__,
                LongTermScheduledScanRunRecord.__table__,
                UserPushPreferenceRecord.__table__,
                Symbol.__table__,
                Watchlist.__table__,
                WatchlistSymbol.__table__,
            ],
            checkfirst=True,
        )

    def insert_snapshot(self, result: LongTermResearchResult) -> None:
        record = LongTermResearchSnapshotRecord(
            symbol=result.symbol,
            as_of=result.as_of,
            price=result.price,
            research_state=result.research_state.value,
            evidence_quality=result.evidence_quality.value,
            factors_json=result.factors.model_dump(mode="json"),
            positive_evidence_json=result.positive_evidence,
            negative_evidence_json=result.negative_evidence,
            contradictions_json=result.contradictions,
            missing_evidence_json=result.missing_evidence,
            reason=result.reason,
            what_would_change_state=result.what_would_change_state,
            market_data_provider=result.market_data_provider,
            fundamentals_provider=result.fundamentals_provider,
            pipeline_version=result.pipeline_version,
            ai_summary=result.ai_summary,
        )
        self._session.add(record)
        self._session.commit()

    def _to_result(self, record: LongTermResearchSnapshotRecord) -> LongTermResearchResult:
        return LongTermResearchResult(
            symbol=record.symbol,
            as_of=record.as_of,
            price=record.price,
            research_state=LongTermResearchState(record.research_state),
            factors=LongTermFactorBundle.model_validate(record.factors_json),
            evidence_quality=LongTermEvidenceQuality(record.evidence_quality),
            positive_evidence=list(record.positive_evidence_json or []),
            negative_evidence=list(record.negative_evidence_json or []),
            contradictions=list(record.contradictions_json or []),
            missing_evidence=list(record.missing_evidence_json or []),
            reason=record.reason,
            what_would_change_state=record.what_would_change_state,
            market_data_provider=record.market_data_provider,
            fundamentals_provider=record.fundamentals_provider,
            pipeline_version=record.pipeline_version,
            ai_summary=record.ai_summary,
        )

    def get_latest_snapshot(self, symbol: str) -> Optional[LongTermResearchResult]:
        record = self._session.execute(
            select(LongTermResearchSnapshotRecord)
            .where(LongTermResearchSnapshotRecord.symbol == symbol)
            .order_by(LongTermResearchSnapshotRecord.as_of.desc())
            .limit(1)
        ).scalar_one_or_none()
        return self._to_result(record) if record is not None else None

    def list_latest_snapshots(self, symbols: list[str]) -> dict[str, LongTermResearchResult]:
        return {
            symbol: result
            for symbol in symbols
            if (result := self.get_latest_snapshot(symbol)) is not None
        }

    def list_user_watchlist_symbols(self, user_id: UUID) -> list[str]:
        rows = self._session.execute(
            select(Symbol.ticker)
            .join(WatchlistSymbol, WatchlistSymbol.symbol_id == Symbol.id)
            .join(Watchlist, Watchlist.id == WatchlistSymbol.watchlist_id)
            .where(Watchlist.user_id == user_id)
            .order_by(Symbol.ticker)
        ).scalars()
        return list(rows)

    def list_all_watchlist_symbols_union(self) -> list[str]:
        rows = self._session.execute(
            select(Symbol.ticker)
            .join(WatchlistSymbol, WatchlistSymbol.symbol_id == Symbol.id)
            .distinct()
            .order_by(Symbol.ticker)
        ).scalars()
        return list(rows)

    def list_push_eligible_user_ids(self, symbol: str) -> list[UUID]:
        rows = self._session.execute(
            select(UserPushPreferenceRecord.user_id)
            .join(Watchlist, Watchlist.user_id == UserPushPreferenceRecord.user_id)
            .join(WatchlistSymbol, WatchlistSymbol.watchlist_id == Watchlist.id)
            .join(Symbol, Symbol.id == WatchlistSymbol.symbol_id)
            .where(
                Symbol.ticker == symbol,
                UserPushPreferenceRecord.long_term_push_enabled.is_(True),
                UserPushPreferenceRecord.pushover_user_key_encrypted.is_not(None),
            )
            .distinct()
        ).scalars()
        return list(rows)

    def _get_or_create_preference_row(self, user_id: UUID) -> UserPushPreferenceRecord:
        row = self._session.execute(
            select(UserPushPreferenceRecord).where(UserPushPreferenceRecord.user_id == user_id)
        ).scalar_one_or_none()
        if row is not None:
            return row
        row = UserPushPreferenceRecord(user_id=user_id)
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return row

    def get_long_term_push_enabled(self, user_id: UUID) -> bool:
        row = self._session.execute(
            select(UserPushPreferenceRecord).where(UserPushPreferenceRecord.user_id == user_id)
        ).scalar_one_or_none()
        return bool(row.long_term_push_enabled) if row is not None else False

    def set_long_term_push_enabled(self, user_id: UUID, enabled: bool) -> None:
        row = self._get_or_create_preference_row(user_id)
        row.long_term_push_enabled = enabled
        self._session.commit()

    def get_user_pushover_key_encrypted(self, user_id: UUID) -> Optional[str]:
        row = self._session.execute(
            select(UserPushPreferenceRecord).where(UserPushPreferenceRecord.user_id == user_id)
        ).scalar_one_or_none()
        return row.pushover_user_key_encrypted if row is not None else None

    def claim_scheduled_scan_run(self, *, run_date: str, as_of: datetime, symbol_count: int) -> bool:
        existing = self._session.execute(
            select(LongTermScheduledScanRunRecord).where(
                LongTermScheduledScanRunRecord.run_date == run_date
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False

        record = LongTermScheduledScanRunRecord(
            run_date=run_date, as_of=as_of, symbol_count=symbol_count
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            # A concurrent scheduled trigger (e.g. an overlapping/retried
            # cron ping) won the race -- treat exactly like "already ran
            # today," never a crash.
            self._session.rollback()
            return False
        return True
