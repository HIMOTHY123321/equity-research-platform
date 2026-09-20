"""Phase 12 (#F/#G/#P): persistence for the forecast ledger, outcome
resolutions, and versioned validation-gate records. Same ABC + SqlAlchemy-
implementation pattern as every repository since Phase 7. `save_forecast`/
`save_outcome`/`save_gate_version` are idempotent on their deterministic
business key -- the mechanical enforcement behind "forecast cannot be
edited" (#F): a second save for the same `forecast_id` is a no-op, never an
overwrite. There is no `update_forecast` method anywhere in this module,
by design.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    Base,
    ForecastOutcomeRecord,
    ForwardForecastRecord,
    ForwardValidationGateResultRecord,
    ForwardValidationGateVersionRecord,
)
from app.forecasting.schemas import ForecastOutcome, ForwardForecast


class ForecastRepository(ABC):
    @abstractmethod
    def save_forecast(self, forecast: ForwardForecast) -> str: ...

    @abstractmethod
    def get_forecast(self, forecast_id: str) -> Optional[ForwardForecast]: ...

    @abstractmethod
    def list_forecasts(
        self,
        *,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 500,
    ) -> list[ForwardForecast]: ...

    @abstractmethod
    def save_outcome(self, outcome: ForecastOutcome) -> str: ...

    @abstractmethod
    def get_outcome_for_forecast(self, forecast_id: str) -> Optional[ForecastOutcome]: ...

    @abstractmethod
    def list_outcomes(self, forecast_ids: list[str]) -> dict[str, ForecastOutcome]: ...

    @abstractmethod
    def save_gate_version(self, gate_version: str, criteria: dict) -> str: ...

    @abstractmethod
    def get_gate_version(self, gate_version: str) -> Optional[dict]: ...

    @abstractmethod
    def save_gate_result(self, gate_version: str, evaluated_at, decision: str, payload: dict) -> str: ...

    @abstractmethod
    def get_latest_gate_result(self, gate_version: Optional[str] = None) -> Optional[dict]: ...


class SqlAlchemyForecastRepository(ForecastRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        Base.metadata.create_all(
            bind=session.get_bind(),
            tables=[
                ForwardForecastRecord.__table__,
                ForecastOutcomeRecord.__table__,
                ForwardValidationGateVersionRecord.__table__,
                ForwardValidationGateResultRecord.__table__,
            ],
            checkfirst=True,
        )

    def save_forecast(self, forecast: ForwardForecast) -> str:
        existing = self._session.execute(
            select(ForwardForecastRecord).where(ForwardForecastRecord.forecast_id == forecast.forecast_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing.forecast_id
        row = ForwardForecastRecord(
            forecast_id=forecast.forecast_id,
            schema_version=forecast.schema_version,
            created_at=forecast.created_at,
            market_as_of=forecast.market_as_of,
            symbol=forecast.symbol,
            timeframe=forecast.timeframe,
            forecast_category=forecast.forecast_category.value,
            forecast_value=forecast.forecast_value,
            forecast_horizon_bars=forecast.forecast_horizon_bars,
            evidence_packet_id=forecast.evidence_packet_id,
            origin=forecast.origin.value,
            status=forecast.status.value,
            run_mode=forecast.run_mode.value,
            payload=forecast.model_dump(mode="json"),
        )
        self._session.add(row)
        self._session.commit()
        return row.forecast_id

    def get_forecast(self, forecast_id: str) -> Optional[ForwardForecast]:
        row = self._session.execute(
            select(ForwardForecastRecord).where(ForwardForecastRecord.forecast_id == forecast_id)
        ).scalar_one_or_none()
        return ForwardForecast.model_validate(row.payload) if row is not None else None

    def list_forecasts(
        self, *, symbol=None, timeframe=None, status=None, limit: int = 500
    ) -> list[ForwardForecast]:
        query = select(ForwardForecastRecord)
        if symbol is not None:
            query = query.where(ForwardForecastRecord.symbol == symbol)
        if timeframe is not None:
            query = query.where(ForwardForecastRecord.timeframe == timeframe)
        if status is not None:
            query = query.where(ForwardForecastRecord.status == status)
        query = query.order_by(ForwardForecastRecord.created_at.desc()).limit(limit)
        rows = self._session.execute(query).scalars()
        return [ForwardForecast.model_validate(r.payload) for r in rows]

    def save_outcome(self, outcome: ForecastOutcome) -> str:
        existing = self._session.execute(
            select(ForecastOutcomeRecord).where(ForecastOutcomeRecord.forecast_id == outcome.forecast_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing.outcome_id
        row = ForecastOutcomeRecord(
            outcome_id=outcome.outcome_id,
            forecast_id=outcome.forecast_id,
            outcome=outcome.outcome.value,
            resolved_at=outcome.resolved_at,
            payload=outcome.model_dump(mode="json"),
        )
        self._session.add(row)
        self._session.commit()
        return row.outcome_id

    def get_outcome_for_forecast(self, forecast_id: str) -> Optional[ForecastOutcome]:
        row = self._session.execute(
            select(ForecastOutcomeRecord).where(ForecastOutcomeRecord.forecast_id == forecast_id)
        ).scalar_one_or_none()
        return ForecastOutcome.model_validate(row.payload) if row is not None else None

    def list_outcomes(self, forecast_ids: list[str]) -> dict[str, ForecastOutcome]:
        if not forecast_ids:
            return {}
        rows = self._session.execute(
            select(ForecastOutcomeRecord).where(ForecastOutcomeRecord.forecast_id.in_(forecast_ids))
        ).scalars()
        return {r.forecast_id: ForecastOutcome.model_validate(r.payload) for r in rows}

    def save_gate_version(self, gate_version: str, criteria: dict) -> str:
        existing = self._session.execute(
            select(ForwardValidationGateVersionRecord).where(
                ForwardValidationGateVersionRecord.gate_version == gate_version
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing.gate_version
        row = ForwardValidationGateVersionRecord(gate_version=gate_version, criteria=criteria)
        self._session.add(row)
        self._session.commit()
        return row.gate_version

    def get_gate_version(self, gate_version: str) -> Optional[dict]:
        row = self._session.execute(
            select(ForwardValidationGateVersionRecord).where(
                ForwardValidationGateVersionRecord.gate_version == gate_version
            )
        ).scalar_one_or_none()
        return row.criteria if row is not None else None

    def save_gate_result(self, gate_version: str, evaluated_at, decision: str, payload: dict) -> str:
        row = ForwardValidationGateResultRecord(
            gate_version=gate_version, evaluated_at=evaluated_at, decision=decision, payload=payload
        )
        self._session.add(row)
        self._session.commit()
        return str(row.id)

    def get_latest_gate_result(self, gate_version: Optional[str] = None) -> Optional[dict]:
        query = select(ForwardValidationGateResultRecord)
        if gate_version is not None:
            query = query.where(ForwardValidationGateResultRecord.gate_version == gate_version)
        query = query.order_by(ForwardValidationGateResultRecord.evaluated_at.desc()).limit(1)
        row = self._session.execute(query).scalar_one_or_none()
        return row.payload if row is not None else None
