"""Phase 14: Alert Center + preferences API. Thin orchestration only --
every alert is already constructed and persisted by app.alerts.service; this
module only reads/acknowledges what already exists (§16/§17/§21/§43)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository, SqlAlchemyAlertRepository
from app.alerts.schemas import DEFAULT_ALERT_PREFERENCES, AlertEvent, AlertPreference, AlertType
from app.database.session import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _alert_repository(db: Session = Depends(get_db)) -> AlertRepository:
    return SqlAlchemyAlertRepository(db)


class UnreadCountResponse(BaseModel):
    count: int


class ProspectiveCountResponse(BaseModel):
    count: int
    """§33/§34: genuine, post-deployment prospective observations only --
    never incremented by dev-fixture or historical-replay alerts, see
    app.alerts.prospective.is_prospective_eligible."""


class AcknowledgeAllResponse(BaseModel):
    acknowledged: int


class SetPreferenceRequest(BaseModel):
    enabled: bool


@router.get("", response_model=list[AlertEvent])
def list_alerts(
    symbol: str | None = Query(None),
    alert_type: str | None = Query(None),
    severity: str | None = Query(None),
    origin: str | None = Query(None),
    unread_only: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    repository: AlertRepository = Depends(_alert_repository),
) -> list[AlertEvent]:
    return repository.list_events(
        symbol=symbol,
        alert_type=alert_type,
        severity=severity,
        origin=origin,
        unread_only=unread_only,
        limit=limit,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    symbol: str | None = Query(None),
    repository: AlertRepository = Depends(_alert_repository),
) -> UnreadCountResponse:
    return UnreadCountResponse(count=repository.unread_count(symbol=symbol))


@router.get("/prospective-count", response_model=ProspectiveCountResponse)
def get_prospective_count(
    repository: AlertRepository = Depends(_alert_repository),
) -> ProspectiveCountResponse:
    return ProspectiveCountResponse(count=repository.count_prospective_observations())


@router.get("/preferences", response_model=list[AlertPreference])
def get_preferences(repository: AlertRepository = Depends(_alert_repository)) -> list[AlertPreference]:
    """Every AlertType, with stored overrides applied over the defaults --
    never a partial list, so the UI never has to know the default table
    itself (§21)."""
    overrides = {p.alert_type: p.enabled for p in repository.get_preferences()}
    return [
        AlertPreference(alert_type=t, enabled=overrides.get(t, DEFAULT_ALERT_PREFERENCES.get(t, True)))
        for t in AlertType
    ]


@router.put("/preferences/{alert_type}", response_model=AlertPreference)
def set_preference(
    alert_type: str,
    payload: SetPreferenceRequest,
    repository: AlertRepository = Depends(_alert_repository),
) -> AlertPreference:
    try:
        parsed_type = AlertType(alert_type)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown alert type {alert_type!r}") from exc
    repository.set_preference(parsed_type, payload.enabled)
    return AlertPreference(alert_type=parsed_type, enabled=payload.enabled)


@router.post("/{alert_id}/acknowledge", status_code=204, response_model=None)
def acknowledge_alert(alert_id: str, repository: AlertRepository = Depends(_alert_repository)) -> None:
    if repository.get_event(alert_id) is None:
        raise HTTPException(status_code=404, detail=f"AlertEvent {alert_id!r} not found")
    repository.acknowledge(alert_id, acknowledged_at=datetime.now(timezone.utc))


@router.post("/acknowledge-all", response_model=AcknowledgeAllResponse)
def acknowledge_all(
    symbol: str | None = Query(None),
    repository: AlertRepository = Depends(_alert_repository),
) -> AcknowledgeAllResponse:
    count = repository.acknowledge_all(acknowledged_at=datetime.now(timezone.utc), symbol=symbol)
    return AcknowledgeAllResponse(acknowledged=count)
