"""Phase 16.1 (§5): per-user monitoring subscriptions API -- "which symbols
does THIS user want alerted." Auth required on every route (mirrors
app.api.routes.watchlist's own pattern); distinct from the SYSTEM RESEARCH
UNIVERSE (app.monitoring.universe.MonitoringUniverse), which decides which
symbols get background computation at all and is never directly exposed
here."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository, SqlAlchemyAlertRepository
from app.alerts.schemas import MonitoringSubscription
from app.auth.dependencies import get_current_user
from app.database.models import User
from app.database.session import get_db

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


def _alert_repository(db: Session = Depends(get_db)) -> AlertRepository:
    return SqlAlchemyAlertRepository(db)


@router.get("", response_model=list[MonitoringSubscription])
def list_monitoring(
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> list[MonitoringSubscription]:
    return repository.list_user_monitoring_subscriptions(current_user.id)


@router.post("/{symbol}", response_model=MonitoringSubscription)
def enable_monitoring(
    symbol: str,
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> MonitoringSubscription:
    normalized = symbol.upper()
    existing = next(
        (s for s in repository.list_user_monitoring_subscriptions(current_user.id) if s.symbol == normalized),
        None,
    )
    subscription = MonitoringSubscription(
        symbol=normalized,
        enabled=True,
        decision_monitoring_enabled=True,
        preferred_timeframes=existing.preferred_timeframes if existing else [],
        added_at=existing.added_at if existing else datetime.now(timezone.utc),
    )
    repository.upsert_user_monitoring_subscription(current_user.id, subscription)
    return subscription


@router.delete("/{symbol}", status_code=204, response_model=None)
def disable_monitoring(
    symbol: str,
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> None:
    repository.remove_user_monitoring_subscription(current_user.id, symbol.upper())
