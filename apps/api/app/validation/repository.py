"""Phase 15: persistence for the Signal Validation Gate -- same immutable
versioned-criteria + immutable-result-row pattern as
`app.forecasting.repository`'s gate methods, applied to
`SignalGateVersionRecord`/`SignalGateResultRecord`."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Base, SignalGateResultRecord, SignalGateVersionRecord


class SignalGateRepository(ABC):
    @abstractmethod
    def save_gate_version(self, gate_version: str, criteria: dict) -> str: ...

    @abstractmethod
    def get_gate_version(self, gate_version: str) -> Optional[dict]: ...

    @abstractmethod
    def save_gate_result(
        self, gate_version: str, evaluated_at: datetime, decision: str, payload: dict
    ) -> str: ...

    @abstractmethod
    def get_latest_gate_result(self, gate_version: Optional[str] = None) -> Optional[dict]: ...

    @abstractmethod
    def list_gate_results(self, gate_version: Optional[str] = None, limit: int = 100) -> list[dict]: ...


class SqlAlchemySignalGateRepository(SignalGateRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        Base.metadata.create_all(
            bind=session.get_bind(),
            tables=[SignalGateVersionRecord.__table__, SignalGateResultRecord.__table__],
            checkfirst=True,
        )

    def save_gate_version(self, gate_version: str, criteria: dict) -> str:
        existing = self._session.execute(
            select(SignalGateVersionRecord).where(SignalGateVersionRecord.gate_version == gate_version)
        ).scalar_one_or_none()
        if existing is not None:
            return existing.gate_version
        row = SignalGateVersionRecord(gate_version=gate_version, criteria=criteria)
        self._session.add(row)
        self._session.commit()
        return row.gate_version

    def get_gate_version(self, gate_version: str) -> Optional[dict]:
        row = self._session.execute(
            select(SignalGateVersionRecord).where(SignalGateVersionRecord.gate_version == gate_version)
        ).scalar_one_or_none()
        return row.criteria if row is not None else None

    def save_gate_result(
        self, gate_version: str, evaluated_at: datetime, decision: str, payload: dict
    ) -> str:
        row = SignalGateResultRecord(
            gate_version=gate_version, evaluated_at=evaluated_at, decision=decision, payload=payload
        )
        self._session.add(row)
        self._session.commit()
        return str(row.id)

    def get_latest_gate_result(self, gate_version: Optional[str] = None) -> Optional[dict]:
        query = select(SignalGateResultRecord)
        if gate_version is not None:
            query = query.where(SignalGateResultRecord.gate_version == gate_version)
        query = query.order_by(SignalGateResultRecord.evaluated_at.desc()).limit(1)
        row = self._session.execute(query).scalar_one_or_none()
        return row.payload if row is not None else None

    def list_gate_results(self, gate_version: Optional[str] = None, limit: int = 100) -> list[dict]:
        query = select(SignalGateResultRecord)
        if gate_version is not None:
            query = query.where(SignalGateResultRecord.gate_version == gate_version)
        query = query.order_by(SignalGateResultRecord.evaluated_at.desc()).limit(limit)
        rows = self._session.execute(query).scalars().all()
        return [r.payload for r in rows]
