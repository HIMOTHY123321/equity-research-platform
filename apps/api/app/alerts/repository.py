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
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.models import (
    AlertAcknowledgementRecord,
    AlertEventRecord,
    AlertHorizonOutcomeRecord,
    AlertOutcomeRecord,
    AlertPreferenceRecord,
    Base,
    MonitoringSubscriptionRecord,
    UserAlertDeliveryRecord,
    UserAlertPreferenceRecord,
    UserMonitoringSubscriptionRecord,
    UserPushPreferenceRecord,
)
from app.alerts.prospective import is_prospective_eligible
from app.alerts.schemas import (
    DEFAULT_ALERT_PREFERENCES,
    AlertEvent,
    AlertHorizonOutcome,
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

    # ----------------------------------------------------------- Phase 16.1
    # Per-user monitoring/delivery -- see app.database.models's Phase 16.1
    # section docstring for the SYSTEM RESEARCH UNIVERSE vs USER MONITORING
    # SUBSCRIPTIONS distinction these methods implement.

    @abstractmethod
    def list_user_monitoring_subscriptions(self, user_id) -> list[MonitoringSubscription]: ...

    @abstractmethod
    def upsert_user_monitoring_subscription(self, user_id, subscription: MonitoringSubscription) -> None: ...

    @abstractmethod
    def remove_user_monitoring_subscription(self, user_id, symbol: str) -> None: ...

    @abstractmethod
    def list_all_monitored_symbols(self) -> list[str]:
        """Distinct symbols with at least one user's ENABLED monitoring
        subscription, across ALL users -- feeds MonitoringUniverse's SYSTEM
        RESEARCH UNIVERSE (app.monitoring.universe), never a per-user
        query."""
        ...

    @abstractmethod
    def list_subscribed_user_ids(self, symbol: str) -> list[UUID]:
        """Every user with an ENABLED UserMonitoringSubscriptionRecord for
        `symbol` -- deliberately NOT filtered by any per-alert-type
        preference. The shared base both in-app delivery (further
        filtered by alert-type preference, see
        deliver_alert_to_subscribed_users below) and push delivery
        (further filtered by push preference + destination key, see
        app.alerts.push) build on -- push is intentionally its OWN
        channel/opt-in, independent of whether a user has muted a given
        alert type in-app (Phase 20.1)."""
        ...

    @abstractmethod
    def deliver_alert_to_subscribed_users(self, event: AlertEvent) -> list[UUID]:
        """Fan-out ONLY -- creates one UserAlertDeliveryRecord per user
        whose enabled UserMonitoringSubscriptionRecord matches
        `event.symbol` (respecting that user's own alert-type preference).
        Must NEVER be mistaken for a second research observation: the
        single, deterministic `event` row this fans out from already
        exists and is never duplicated. Returns the user_ids a NEW
        delivery row was actually created for -- this is the IN-APP
        delivery set; push delivery uses list_subscribed_user_ids
        instead (Phase 20.1), since push must not depend on a user's
        in-app alert-type preference."""
        ...

    @abstractmethod
    def list_user_alerts(
        self,
        user_id,
        *,
        symbol: Optional[str] = None,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        origin: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 200,
    ) -> list[AlertEvent]: ...

    @abstractmethod
    def user_unread_count(self, user_id, *, symbol: Optional[str] = None) -> int: ...

    @abstractmethod
    def acknowledge_user_delivery(self, user_id, alert_id: str, *, acknowledged_at: datetime) -> bool:
        """Returns False if this user has no delivery for `alert_id` at
        all (never touches another user's row, and never raises -- a
        missing delivery for THIS user is a 404-worthy condition the route
        layer decides how to report)."""
        ...

    @abstractmethod
    def acknowledge_all_user_deliveries(
        self, user_id, *, acknowledged_at: datetime, symbol: Optional[str] = None
    ) -> int: ...

    @abstractmethod
    def get_user_preferences(self, user_id) -> list[AlertPreference]: ...

    @abstractmethod
    def set_user_preference(self, user_id, alert_type: AlertType, enabled: bool) -> None: ...

    # --------------------------------------------------------------- Phase 20
    # Phone-push delivery (app.alerts.push) -- see UserPushPreferenceRecord's
    # own docstring for why this is a single global per-user switch, not a
    # per-alert-type or per-symbol table.

    @abstractmethod
    def get_user_push_enabled(self, user_id) -> bool:
        """False (the conservative default -- §7 of the spec) when the
        user has never set a preference at all, never True by default."""
        ...

    @abstractmethod
    def set_user_push_enabled(self, user_id, enabled: bool) -> None: ...

    @abstractmethod
    def get_user_pushover_key_encrypted(self, user_id) -> Optional[str]:
        """Returns the raw ENCRYPTED ciphertext (app.notifications.
        secret_crypto) or None if this user has never configured a
        destination key. Callers needing the plaintext (only
        app.alerts.push, to actually send) must decrypt it themselves --
        this repository has no knowledge of `secret_key` and never
        decrypts anything, keeping encryption/decryption concerns
        entirely out of the persistence layer."""
        ...

    @abstractmethod
    def set_user_pushover_key_encrypted(self, user_id, encrypted_key: Optional[str]) -> None:
        """`None` clears the stored key (the user removed their
        destination). Never accepts or stores a plaintext key -- the
        caller (the route layer) is responsible for encrypting first."""
        ...

    @abstractmethod
    def record_push_delivery(
        self, user_id, alert_id: str, *, success: bool, error: Optional[str] = None
    ) -> None:
        """Records the outcome of ONE Pushover send attempt against this
        user's existing UserAlertDeliveryRecord row for `alert_id`, when
        one exists. Phase 20.1: push eligibility no longer implies an
        in-app delivery row exists (a user who opted into push but
        never enabled a given alert type in-app has no
        UserAlertDeliveryRecord for it at all -- see
        list_subscribed_user_ids) -- for that case this is a deliberate
        no-op (the attempt is still logged by app.alerts.push, just not
        persisted per-user), never an error and never a reason to create
        a row that would incorrectly surface in that user's in-app Alert
        Center."""
        ...

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

    @abstractmethod
    def save_horizon_outcome(self, outcome: AlertHorizonOutcome) -> tuple[AlertHorizonOutcome, bool]:
        """Resolve-once per (alert_id, horizon_bars): returns
        (stored_outcome, created), mirroring save_outcome's own contract
        one horizon at a time."""
        ...

    @abstractmethod
    def get_horizon_outcomes_for_alert(self, alert_id: str) -> list[AlertHorizonOutcome]:
        """Only the horizons already resolved for this alert -- a missing
        horizon means pending, never a fabricated value."""
        ...


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
                AlertHorizonOutcomeRecord.__table__,
                UserMonitoringSubscriptionRecord.__table__,
                UserAlertDeliveryRecord.__table__,
                UserAlertPreferenceRecord.__table__,
                UserPushPreferenceRecord.__table__,
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

    # ----------------------------------------------------------- Phase 16.1

    def list_user_monitoring_subscriptions(self, user_id) -> list[MonitoringSubscription]:
        rows = self._session.execute(
            select(UserMonitoringSubscriptionRecord).where(
                UserMonitoringSubscriptionRecord.user_id == user_id
            )
        ).scalars()
        return sorted(
            (
                MonitoringSubscription(
                    symbol=r.symbol,
                    enabled=r.enabled,
                    preferred_timeframes=r.preferred_timeframes or [],
                    decision_monitoring_enabled=r.decision_monitoring_enabled,
                    added_at=r.added_at,
                )
                for r in rows
            ),
            key=lambda s: s.symbol,
        )

    def upsert_user_monitoring_subscription(self, user_id, subscription: MonitoringSubscription) -> None:
        existing = self._session.execute(
            select(UserMonitoringSubscriptionRecord).where(
                UserMonitoringSubscriptionRecord.user_id == user_id,
                UserMonitoringSubscriptionRecord.symbol == subscription.symbol,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.enabled = subscription.enabled
            existing.decision_monitoring_enabled = subscription.decision_monitoring_enabled
            existing.preferred_timeframes = subscription.preferred_timeframes
        else:
            self._session.add(
                UserMonitoringSubscriptionRecord(
                    user_id=user_id,
                    symbol=subscription.symbol,
                    enabled=subscription.enabled,
                    decision_monitoring_enabled=subscription.decision_monitoring_enabled,
                    preferred_timeframes=subscription.preferred_timeframes,
                    added_at=subscription.added_at,
                )
            )
        self._session.commit()

    def remove_user_monitoring_subscription(self, user_id, symbol: str) -> None:
        existing = self._session.execute(
            select(UserMonitoringSubscriptionRecord).where(
                UserMonitoringSubscriptionRecord.user_id == user_id,
                UserMonitoringSubscriptionRecord.symbol == symbol,
            )
        ).scalar_one_or_none()
        if existing is not None:
            self._session.delete(existing)
            self._session.commit()

    def list_all_monitored_symbols(self) -> list[str]:
        rows = self._session.execute(
            select(UserMonitoringSubscriptionRecord.symbol)
            .where(UserMonitoringSubscriptionRecord.enabled.is_(True))
            .distinct()
        ).scalars()
        return sorted(set(rows))

    def list_subscribed_user_ids(self, symbol: str) -> list[UUID]:
        return list(
            self._session.execute(
                select(UserMonitoringSubscriptionRecord.user_id).where(
                    UserMonitoringSubscriptionRecord.symbol == symbol,
                    UserMonitoringSubscriptionRecord.enabled.is_(True),
                )
            )
            .scalars()
            .all()
        )

    def deliver_alert_to_subscribed_users(self, event: AlertEvent) -> list[UUID]:
        subscriber_ids = self.list_subscribed_user_ids(event.symbol)
        if not subscriber_ids:
            return []

        delivered: list[UUID] = []
        for user_id in subscriber_ids:
            if not self._user_preference_enabled(user_id, event.alert_type):
                continue
            existing = self._session.execute(
                select(UserAlertDeliveryRecord).where(
                    UserAlertDeliveryRecord.user_id == user_id,
                    UserAlertDeliveryRecord.alert_id == event.alert_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            self._session.add(
                UserAlertDeliveryRecord(user_id=user_id, alert_id=event.alert_id, symbol=event.symbol)
            )
            delivered.append(user_id)
        if delivered:
            self._session.commit()
        return delivered

    def _user_preference_enabled(self, user_id, alert_type: AlertType) -> bool:
        override = self._session.execute(
            select(UserAlertPreferenceRecord).where(
                UserAlertPreferenceRecord.user_id == user_id,
                UserAlertPreferenceRecord.alert_type == alert_type.value,
            )
        ).scalar_one_or_none()
        if override is not None:
            return override.enabled
        return DEFAULT_ALERT_PREFERENCES.get(alert_type, True)

    def list_user_alerts(
        self,
        user_id,
        *,
        symbol: Optional[str] = None,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        origin: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 200,
    ) -> list[AlertEvent]:
        query = (
            select(AlertEventRecord)
            .join(UserAlertDeliveryRecord, UserAlertDeliveryRecord.alert_id == AlertEventRecord.alert_id)
            .where(UserAlertDeliveryRecord.user_id == user_id)
        )
        if symbol is not None:
            query = query.where(AlertEventRecord.symbol == symbol)
        if alert_type is not None:
            query = query.where(AlertEventRecord.alert_type == alert_type)
        if severity is not None:
            query = query.where(AlertEventRecord.severity == severity)
        if origin is not None:
            query = query.where(AlertEventRecord.origin == origin)
        if unread_only:
            query = query.where(UserAlertDeliveryRecord.acknowledged_at.is_(None))
        query = query.order_by(AlertEventRecord.occurred_at.desc()).limit(limit)
        rows = self._session.execute(query).scalars()
        return [AlertEvent.model_validate(r.payload) for r in rows]

    def user_unread_count(self, user_id, *, symbol: Optional[str] = None) -> int:
        return len(self.list_user_alerts(user_id, symbol=symbol, unread_only=True, limit=100_000))

    def _get_user_delivery(self, user_id, alert_id: str) -> Optional[UserAlertDeliveryRecord]:
        return self._session.execute(
            select(UserAlertDeliveryRecord).where(
                UserAlertDeliveryRecord.user_id == user_id, UserAlertDeliveryRecord.alert_id == alert_id
            )
        ).scalar_one_or_none()

    def acknowledge_user_delivery(self, user_id, alert_id: str, *, acknowledged_at: datetime) -> bool:
        delivery = self._get_user_delivery(user_id, alert_id)
        if delivery is None:
            return False
        if delivery.acknowledged_at is None:
            delivery.acknowledged_at = acknowledged_at
            self._session.commit()
        return True

    def acknowledge_all_user_deliveries(
        self, user_id, *, acknowledged_at: datetime, symbol: Optional[str] = None
    ) -> int:
        unread = self.list_user_alerts(user_id, symbol=symbol, unread_only=True, limit=100_000)
        for event in unread:
            self.acknowledge_user_delivery(user_id, event.alert_id, acknowledged_at=acknowledged_at)
        return len(unread)

    def get_user_preferences(self, user_id) -> list[AlertPreference]:
        rows = self._session.execute(
            select(UserAlertPreferenceRecord).where(UserAlertPreferenceRecord.user_id == user_id)
        ).scalars()
        return [AlertPreference(alert_type=AlertType(r.alert_type), enabled=r.enabled) for r in rows]

    def set_user_preference(self, user_id, alert_type: AlertType, enabled: bool) -> None:
        existing = self._session.execute(
            select(UserAlertPreferenceRecord).where(
                UserAlertPreferenceRecord.user_id == user_id,
                UserAlertPreferenceRecord.alert_type == alert_type.value,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.enabled = enabled
        else:
            self._session.add(
                UserAlertPreferenceRecord(user_id=user_id, alert_type=alert_type.value, enabled=enabled)
            )
        self._session.commit()

    def get_user_push_enabled(self, user_id) -> bool:
        row = self._session.execute(
            select(UserPushPreferenceRecord).where(UserPushPreferenceRecord.user_id == user_id)
        ).scalar_one_or_none()
        return row.push_enabled if row is not None else False

    def set_user_push_enabled(self, user_id, enabled: bool) -> None:
        existing = self._session.execute(
            select(UserPushPreferenceRecord).where(UserPushPreferenceRecord.user_id == user_id)
        ).scalar_one_or_none()
        if existing is not None:
            existing.push_enabled = enabled
        else:
            self._session.add(UserPushPreferenceRecord(user_id=user_id, push_enabled=enabled))
        self._session.commit()

    def get_user_pushover_key_encrypted(self, user_id) -> Optional[str]:
        row = self._session.execute(
            select(UserPushPreferenceRecord).where(UserPushPreferenceRecord.user_id == user_id)
        ).scalar_one_or_none()
        return row.pushover_user_key_encrypted if row is not None else None

    def set_user_pushover_key_encrypted(self, user_id, encrypted_key: Optional[str]) -> None:
        existing = self._session.execute(
            select(UserPushPreferenceRecord).where(UserPushPreferenceRecord.user_id == user_id)
        ).scalar_one_or_none()
        if existing is not None:
            existing.pushover_user_key_encrypted = encrypted_key
        else:
            self._session.add(
                UserPushPreferenceRecord(user_id=user_id, pushover_user_key_encrypted=encrypted_key)
            )
        self._session.commit()

    def record_push_delivery(
        self, user_id, alert_id: str, *, success: bool, error: Optional[str] = None
    ) -> None:
        delivery = self._get_user_delivery(user_id, alert_id)
        if delivery is None:
            return
        delivery.push_status = "sent" if success else "failed"
        delivery.push_attempted_at = datetime.now(timezone.utc)
        delivery.push_error = None if success else error
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

    def save_horizon_outcome(self, outcome: AlertHorizonOutcome) -> tuple[AlertHorizonOutcome, bool]:
        existing = self._session.execute(
            select(AlertHorizonOutcomeRecord).where(
                AlertHorizonOutcomeRecord.alert_id == outcome.alert_id,
                AlertHorizonOutcomeRecord.horizon_bars == outcome.horizon_bars,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return AlertHorizonOutcome.model_validate(existing.payload), False

        row = AlertHorizonOutcomeRecord(
            outcome_id=outcome.outcome_id,
            alert_id=outcome.alert_id,
            horizon_bars=outcome.horizon_bars,
            symbol=outcome.symbol,
            resolved_at=outcome.resolved_at,
            payload=outcome.model_dump(mode="json"),
        )
        self._session.add(row)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self._session.execute(
                select(AlertHorizonOutcomeRecord).where(
                    AlertHorizonOutcomeRecord.alert_id == outcome.alert_id,
                    AlertHorizonOutcomeRecord.horizon_bars == outcome.horizon_bars,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return AlertHorizonOutcome.model_validate(existing.payload), False
            raise
        return outcome, True

    def get_horizon_outcomes_for_alert(self, alert_id: str) -> list[AlertHorizonOutcome]:
        rows = self._session.execute(
            select(AlertHorizonOutcomeRecord).where(AlertHorizonOutcomeRecord.alert_id == alert_id)
        ).scalars()
        return [AlertHorizonOutcome.model_validate(row.payload) for row in rows]
