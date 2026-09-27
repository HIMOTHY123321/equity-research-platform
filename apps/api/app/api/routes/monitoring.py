"""Phase 14: monitoring universe API -- which symbols the background
monitor scans, independent of Watchlist membership (§8/§22/§43)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository, SqlAlchemyAlertRepository
from app.alerts.schemas import MonitoringSubscription
from app.database.session import get_db
from app.monitoring.universe import MonitoringUniverse

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


def _alert_repository(db: Session = Depends(get_db)) -> AlertRepository:
    return SqlAlchemyAlertRepository(db)


def _monitoring_universe(
    alert_repository: AlertRepository = Depends(_alert_repository),
) -> MonitoringUniverse:
    return MonitoringUniverse(alert_repository)


@router.get("", response_model=list[MonitoringSubscription])
def list_monitoring(
    universe: MonitoringUniverse = Depends(_monitoring_universe),
) -> list[MonitoringSubscription]:
    return universe.list_all_subscriptions()


@router.post("/{symbol}", response_model=MonitoringSubscription)
def enable_monitoring(
    symbol: str, universe: MonitoringUniverse = Depends(_monitoring_universe)
) -> MonitoringSubscription:
    return universe.enable(symbol.upper())


@router.delete("/{symbol}", status_code=204, response_model=None)
def disable_monitoring(symbol: str, universe: MonitoringUniverse = Depends(_monitoring_universe)) -> None:
    universe.disable(symbol.upper())
