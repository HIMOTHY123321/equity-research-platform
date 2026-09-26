"""Persistence for AlertEvent/AlertAcknowledgement/AlertPreference/
MonitoringSubscription -- same ABC + SqlAlchemy-implementation pattern as
app.decision_engine.repository.

`record_event` is the exactly-once boundary (§47): it relies on the
database UNIQUE constraint on `dedup_key`, not an in-memory set, so it is
safe across process restarts and concurrent evaluations. A collision is not
an error -- it means "this exact alert already exists," and the existing
row is returned instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.models import (
    AlertAcknowledgementRecord,
    AlertEventRecord,
    AlertOutcomeRecord,
    AlertPreferenceRecord,
    Base,
    MonitoringSubscriptionRecord,
)
from app.alerts.prospective import is_prospective_eligible
from app.alerts.schemas import (
    AlertEvent,
    AlertOutcome,
    AlertPreference,
    AlertType,
    MonitoringSubscription,
)


class AlertRepository(ABC):
    @abstractmethod
    def record_event(self, event: AlertEvent) -> tuple[AlertEvent, bool]:
        """Returns (stored_event, created). `created` is False when an
        event with the same dedup_key already existed -- the pre-existing
        event is returned unchanged, never the caller's new one."""
        ...

    @abstractmethod
    def get_event(self, alert_id: str) -> Optional[AlertEvent]: ...

    @abstractmethod
    def list_events(
        self,
        *,
        symbol: Optional[str] = None,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        origin: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 200,
    ) -> list[AlertEvent]: ...

    @abstractmethod
    def acknowledge(self, alert_id: str, *, acknowledged_at: datetime) -> None: ...

    @abstractmethod
    def acknowledge_all(self, *, acknowledged_at: datetime, symbol: Optional[str] = None) -> int: ...

    @abstractmethod
    def is_acknowledged(self, alert_id: str) -> bool: ...

    @abstractmethod
    def unread_count(self, *, symbol: Optional[str] = None) -> int: ...

    @abstractmethod
    def get_preferences(self) -> list[AlertPreference]: ...

    @abstractmethod
    def set_preference(self, alert_type: AlertType, enabled: bool) -> None: ...

    @abstractmethod
    def list_monitoring_subscriptions(self) -> list[MonitoringSubscription]: ...

    @abstractmethod
    def upsert_monitoring_subscription(self, subscription: MonitoringSubscription) -> None: ...

    @abstractmethod
    def remove_monitoring_subscription(self, symbol: str) -> None: ...

    @abstractmethod
    def count_prospective_observations(self, decision_repository) -> int:
        """§33/§34, hardened Phase 14.1 §4: how many AlertEvents are
        genuine, post-deployment, PROVENANCE-VERIFIED candidates for
        Forward Validation -- see app.alerts.prospective.is_prospective_
        eligible for the full rule (never trusts `origin` alone).
        `decision_repository` is required: it's the independent source of
        truth eligibility is checked against."""
        ...

    @abstractmethod
    def count_resolved_prospective_observations(self) -> int:
        """§Phase-14.1-5: only RESOLVED (see app.alerts.resolver) eligible
        prospective alerts count toward Forward Validation -- creating an
        alert alone must never increment this."""
        ...

    @abstractmethod
    def save_outcome(self, outcome: AlertOutcome) -> tuple[AlertOutcome, bool]:
        """Resolve-once: returns (stored_outcome, created). `created` is
        False when an outcome for this alert_id already existed -- the
        existing row is returned unchanged, mirroring record_event's own
        exactly-once contract."""
        ...

    @abstractmethod
    def get_outcome_for_alert(self, alert_id: str) -> Optional[AlertOutcome]: ...


class SqlAlchemyAlertRepository(AlertRepository):
    def __init__(self, session: Session) -> None:
        self._session = session
        Base.metadata.create_all(
            bind=session.get_bind(),
            tables=[
                AlertEventRecord.__table__,
                AlertAcknowledgementRecord.__table__,
                AlertPreferenceRecord.__table__,
                MonitoringSubscriptionRecord.__table__,
                AlertOutcomeRecord.__table__,
            ],
            checkfirst=True,
        )

    def record_event(self, event: AlertEvent) -> tuple[AlertEvent, bool]:
        existing = self._session.execute(
            select(AlertEventRecord).where(AlertEventRecord.dedup_key == event.dedup_key)
        ).scalar_one_or_none()
        if existing is not None:
            return AlertEvent.model_validate(existing.payload), False

        row = AlertEventRecord(
            alert_id=event.alert_id,
            symbol=event.symbol,
            decision_plan_id=event.decision_plan_id,
            alert_type=event.alert_type.value,
            severity=event.severity.value,
            origin=event.origin.value,
            occurred_at=event.occurred_at,
            dedup_key=event.dedup_key,
            payload=event.model_dump(mode="json"),
        )
        self._session.add(row)
        try:
            self._session.commit()
        except IntegrityError:
            # Lost a race against a concurrent evaluation that inserted the
            # same dedup_key first -- the other insert wins, this one backs
            # off and returns what actually landed.
            self._session.rollback()
            existing = self._session.execute(
                select(AlertEventRecord).where(AlertEventRecord.dedup_key == event.dedup_key)
            ).scalar_one_or_none()
            if existing is not None:
                return AlertEvent.model_validate(existing.payload), False
            raise
        return event, True

    def get_event(self, alert_id: str) -> Optional[AlertEvent]:
        row = self._session.execute(
            select(AlertEventRecord).where(AlertEventRecord.alert_id == alert_id)
        ).scalar_one_or_none()
        return AlertEvent.model_validate(row.payload) if row is not None else None

    def list_events(
        self,
        *,
        symbol: Optional[str] = None,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        origin: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 200,
    ) -> list[AlertEvent]:
        query = select(AlertEventRecord)
        if symbol is not None:
            query = query.where(AlertEventRecord.symbol == symbol)
        if alert_type is not None:
            query = query.where(AlertEventRecord.alert_type == alert_type)
        if severity is not None:
            query = query.where(AlertEventRecord.severity == severity)
        if origin is not None:
            query = query.where(AlertEventRecord.origin == origin)
        if unread_only:
            read_ids = select(AlertAcknowledgementRecord.alert_id)
            query = query.where(AlertEventRecord.alert_id.not_in(read_ids))
        query = query.order_by(AlertEventRecord.occurred_at.desc()).limit(limit)
        rows = self._session.execute(query).scalars()
        return [AlertEvent.model_validate(r.payload) for r in rows]

    def acknowledge(self, alert_id: str, *, acknowledged_at: datetime) -> None:
        existing = self._session.execute(
            select(AlertAcknowledgementRecord).where(AlertAcknowledgementRecord.alert_id == alert_id)
        ).scalar_one_or_none()
        if existing is not None:
            return
        self._session.add(
            AlertAcknowledgementRecord(alert_id=alert_id, acknowledged_at=acknowledged_at)
        )
        self._session.commit()

    def acknowledge_all(self, *, acknowledged_at: datetime, symbol: Optional[str] = None) -> int:
        unread = self.list_events(symbol=symbol, unread_only=True, limit=100_000)
        for event in unread:
            self.acknowledge(event.alert_id, acknowledged_at=acknowledged_at)
        return len(unread)

    def is_acknowledged(self, alert_id: str) -> bool:
        existing = self._session.execute(
            select(AlertAcknowledgementRecord).where(AlertAcknowledgementRecord.alert_id == alert_id)
        ).scalar_one_or_none()
        return existing is not None

    def unread_count(self, *, symbol: Optional[str] = None) -> int:
        return len(self.list_events(symbol=symbol, unread_only=True, limit=100_000))

    def get_preferences(self) -> list[AlertPreference]:
        rows = self._session.execute(select(AlertPreferenceRecord)).scalars()
        return [AlertPreference(alert_type=AlertType(r.alert_type), enabled=r.enabled) for r in rows]

    def set_preference(self, alert_type: AlertType, enabled: bool) -> None:
        existing = self._session.execute(
            select(AlertPreferenceRecord).where(AlertPreferenceRecord.alert_type == alert_type.value)
        ).scalar_one_or_none()
        if existing is not None:
            existing.enabled = enabled
        else:
            self._session.add(AlertPreferenceRecord(alert_type=alert_type.value, enabled=enabled))
        self._session.commit()

    def list_monitoring_subscriptions(self) -> list[MonitoringSubscription]:
        rows = self._session.execute(select(MonitoringSubscriptionRecord)).scalars()
        return [
            MonitoringSubscription(
                symbol=r.symbol,
                enabled=r.enabled,
                preferred_timeframes=r.preferred_timeframes or [],
                decision_monitoring_enabled=r.decision_monitoring_enabled,
                added_at=r.added_at,
            )
            for r in rows
        ]

    def upsert_monitoring_subscription(self, subscription: MonitoringSubscription) -> None:
        existing = self._session.execute(
            select(MonitoringSubscriptionRecord).where(
                MonitoringSubscriptionRecord.symbol == subscription.symbol
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.enabled = subscription.enabled
            existing.decision_monitoring_enabled = subscription.decision_monitoring_enabled
            existing.preferred_timeframes = subscription.preferred_timeframes
        else:
            self._session.add(
                MonitoringSubscriptionRecord(
                    symbol=subscription.symbol,
                    enabled=subscription.enabled,
                    decision_monitoring_enabled=subscription.decision_monitoring_enabled,
                    preferred_timeframes=subscription.preferred_timeframes,
                    added_at=subscription.added_at,
                )
            )
        self._session.commit()

    def remove_monitoring_subscription(self, symbol: str) -> None:
        existing = self._session.execute(
            select(MonitoringSubscriptionRecord).where(MonitoringSubscriptionRecord.symbol == symbol)
        ).scalar_one_or_none()
        if existing is not None:
            self._session.delete(existing)
            self._session.commit()

    def count_prospective_observations(self, decision_repository) -> int:
        rows = self._session.execute(
            select(AlertEventRecord).where(AlertEventRecord.origin == "live_prospective")
        ).scalars()
        candidates = (AlertEvent.model_validate(r.payload) for r in rows)
        return sum(1 for event in candidates if is_prospective_eligible(event, decision_repository))

    def count_resolved_prospective_observations(self, decision_repository) -> int:
        resolved_alert_ids = {
            row.alert_id for row in self._session.execute(select(AlertOutcomeRecord)).scalars()
        }
        if not resolved_alert_ids:
            return 0
        rows = self._session.execute(
            select(AlertEventRecord).where(
                AlertEventRecord.origin == "live_prospective",
                AlertEventRecord.alert_id.in_(resolved_alert_ids),
            )
        ).scalars()
        candidates = (AlertEvent.model_validate(r.payload) for r in rows)
        return sum(1 for event in candidates if is_prospective_eligible(event, decision_repository))

    def save_outcome(self, outcome: AlertOutcome) -> tuple[AlertOutcome, bool]:
        existing = self._session.execute(
            select(AlertOutcomeRecord).where(AlertOutcomeRecord.alert_id == outcome.alert_id)
        ).scalar_one_or_none()
        if existing is not None:
            return AlertOutcome.model_validate(existing.payload), False

        row = AlertOutcomeRecord(
            outcome_id=outcome.outcome_id,
            alert_id=outcome.alert_id,
            symbol=outcome.symbol,
            resolved_at=outcome.resolved_at,
            payload=outcome.model_dump(mode="json"),
        )
        self._session.add(row)
        try:
            self._session.commit()
        except IntegrityError:
            # Lost a race against a concurrent resolver pass -- the other
            # insert wins (§Phase-14.1-5's "repeated resolver runs cannot
            # duplicate outcomes", same exactly-once discipline as
            # record_event).
            self._session.rollback()
            existing = self._session.execute(
                select(AlertOutcomeRecord).where(AlertOutcomeRecord.alert_id == outcome.alert_id)
            ).scalar_one_or_none()
            if existing is not None:
                return AlertOutcome.model_validate(existing.payload), False
            raise
        return outcome, True

    def get_outcome_for_alert(self, alert_id: str) -> Optional[AlertOutcome]:
        row = self._session.execute(
            select(AlertOutcomeRecord).where(AlertOutcomeRecord.alert_id == alert_id)
        ).scalar_one_or_none()
        return AlertOutcome.model_validate(row.payload) if row is not None else None
