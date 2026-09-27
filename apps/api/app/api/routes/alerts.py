"""Phase 14/16.1: Alert Center + preferences API. Every route except
`prospective-count` is now user-scoped (auth required) -- a user only ever
sees, acknowledges, or configures preferences for their OWN
UserAlertDeliveryRecord rows, never another user's and never the raw
global AlertEventRecord table directly. `prospective-count` stays
DELIBERATELY unauthenticated and un-scoped: Forward Validation research
counts must reflect the single shared, deterministic alert stream, never
inflate because more users started monitoring the same symbol (§15)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository, SqlAlchemyAlertRepository
from app.alerts.schemas import DEFAULT_ALERT_PREFERENCES, AlertEvent, AlertPreference, AlertType
from app.auth.dependencies import get_current_user
from app.database.models import User
from app.database.session import get_db
from app.decision_engine.repository import DecisionEngineRepository, SqlAlchemyDecisionEngineRepository

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _alert_repository(db: Session = Depends(get_db)) -> AlertRepository:
    return SqlAlchemyAlertRepository(db)


def _decision_repository(db: Session = Depends(get_db)) -> DecisionEngineRepository:
    return SqlAlchemyDecisionEngineRepository(db)


class UnreadCountResponse(BaseModel):
    count: int


class ProspectiveCountResponse(BaseModel):
    count: int
    """§33/§34: genuine, post-deployment, provenance-verified prospective
    observations -- never incremented by dev-fixture/historical-replay/
    synthetic alerts, see app.alerts.prospective.is_prospective_eligible.
    Deliberately GLOBAL/shared (§15, Phase 16.1) -- never joined through
    UserAlertDeliveryRecord, so N users monitoring the same symbol can
    never inflate this count."""
    resolved: int
    """§Phase-14.1-5: of `count`, how many have an actual resolved outcome
    (app.alerts.resolver) -- creating an eligible alert alone never
    increments this, only a completed resolution does."""


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
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> list[AlertEvent]:
    return repository.list_user_alerts(
        current_user.id,
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
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> UnreadCountResponse:
    return UnreadCountResponse(count=repository.user_unread_count(current_user.id, symbol=symbol))


@router.get("/prospective-count", response_model=ProspectiveCountResponse)
def get_prospective_count(
    repository: AlertRepository = Depends(_alert_repository),
    decision_repository: DecisionEngineRepository = Depends(_decision_repository),
) -> ProspectiveCountResponse:
    return ProspectiveCountResponse(
        count=repository.count_prospective_observations(decision_repository),
        resolved=repository.count_resolved_prospective_observations(decision_repository),
    )


@router.get("/preferences", response_model=list[AlertPreference])
def get_preferences(
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> list[AlertPreference]:
    """Every AlertType, with THIS user's stored overrides applied over the
    defaults -- never a partial list, so the UI never has to know the
    default table itself (§21)."""
    overrides = {p.alert_type: p.enabled for p in repository.get_user_preferences(current_user.id)}
    return [
        AlertPreference(alert_type=t, enabled=overrides.get(t, DEFAULT_ALERT_PREFERENCES.get(t, True)))
        for t in AlertType
    ]


@router.put("/preferences/{alert_type}", response_model=AlertPreference)
def set_preference(
    alert_type: str,
    payload: SetPreferenceRequest,
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> AlertPreference:
    try:
        parsed_type = AlertType(alert_type)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown alert type {alert_type!r}") from exc
    repository.set_user_preference(current_user.id, parsed_type, payload.enabled)
    return AlertPreference(alert_type=parsed_type, enabled=payload.enabled)


@router.post("/{alert_id}/acknowledge", status_code=204, response_model=None)
def acknowledge_alert(
    alert_id: str,
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> None:
    found = repository.acknowledge_user_delivery(
        current_user.id, alert_id, acknowledged_at=datetime.now(timezone.utc)
    )
    if not found:
        raise HTTPException(status_code=404, detail=f"No alert delivery {alert_id!r} for this user")


@router.post("/acknowledge-all", response_model=AcknowledgeAllResponse)
def acknowledge_all(
    symbol: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> AcknowledgeAllResponse:
    count = repository.acknowledge_all_user_deliveries(
        current_user.id, acknowledged_at=datetime.now(timezone.utc), symbol=symbol
    )
    return AcknowledgeAllResponse(acknowledged=count)
