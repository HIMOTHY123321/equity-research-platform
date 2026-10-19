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
from app.config import Settings, get_settings
from app.database.models import User
from app.database.session import get_db
from app.decision_engine.repository import DecisionEngineRepository, SqlAlchemyDecisionEngineRepository
from app.notifications.secret_crypto import encrypt_secret

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


class PushPreferenceResponse(BaseModel):
    enabled: bool
    key_configured: bool
    """Phase 20.1: masked indicator only -- True means THIS user has a
    Pushover destination key stored, never the key itself. The route
    layer never returns a stored key once submitted, by construction
    (this model has no field capable of carrying it)."""


class SetPushPreferenceRequest(BaseModel):
    enabled: bool


class SetPushKeyRequest(BaseModel):
    pushover_user_key: str


class PushKeyResponse(BaseModel):
    key_configured: bool


class PushStatusResponse(BaseModel):
    configured: bool
    """True only when PUSH_NOTIFICATIONS_ENABLED is set AND the Pushover
    app token AND (Phase 20.2) PUSHOVER_KEY_ENCRYPTION_KEY are all present
    server-side (app.config.Settings) -- this is a GLOBAL capability flag
    ("is the feature available on this server at all"), never a
    statement about any particular user. A missing encryption key
    reports False here rather than letting push-key submission or
    dispatch fail unexpectedly later. Never includes the app token or
    encryption key themselves, and (Phase 20.1) there is no global user
    key to leak in the first place -- each user's own destination is
    reported by GET /api/alerts/push-preference's `key_configured`
    instead."""


def _push_settings() -> Settings:
    return get_settings()


@router.get("/push-preference", response_model=PushPreferenceResponse)
def get_push_preference(
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> PushPreferenceResponse:
    """§7: defaults to disabled for every user until they explicitly opt
    in -- never silently true just because a row doesn't exist yet."""
    return PushPreferenceResponse(
        enabled=repository.get_user_push_enabled(current_user.id),
        key_configured=repository.get_user_pushover_key_encrypted(current_user.id) is not None,
    )


@router.put("/push-preference", response_model=PushPreferenceResponse)
def set_push_preference(
    payload: SetPushPreferenceRequest,
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> PushPreferenceResponse:
    repository.set_user_push_enabled(current_user.id, payload.enabled)
    return PushPreferenceResponse(
        enabled=payload.enabled,
        key_configured=repository.get_user_pushover_key_encrypted(current_user.id) is not None,
    )


@router.put("/push-key", response_model=PushKeyResponse)
def set_push_key(
    payload: SetPushKeyRequest,
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
    settings: Settings = Depends(_push_settings),
) -> PushKeyResponse:
    """Phase 20.1: stores THIS authenticated user's OWN Pushover User Key,
    encrypted at rest (app.notifications.secret_crypto) -- never another
    user's, never in plaintext, and never echoed back in this or any
    other response. Submitted over the same authenticated HTTPS session
    every other write in this app uses; no new transport."""
    key = payload.pushover_user_key.strip()
    if not key:
        raise HTTPException(status_code=422, detail="pushover_user_key must not be blank")
    if not settings.pushover_key_encryption_key:
        # Fail safe, never crash: an operator can enable
        # PUSH_NOTIFICATIONS_ENABLED/PUSHOVER_APP_TOKEN without yet having
        # set PUSHOVER_KEY_ENCRYPTION_KEY -- surface that as an ordinary
        # "not configured" response, not an unhandled encryption error.
        raise HTTPException(
            status_code=503, detail="Push notifications are not configured on this server yet"
        )
    encrypted = encrypt_secret(key, encryption_key=settings.pushover_key_encryption_key)
    repository.set_user_pushover_key_encrypted(current_user.id, encrypted)
    return PushKeyResponse(key_configured=True)


@router.delete("/push-key", response_model=PushKeyResponse)
def delete_push_key(
    current_user: User = Depends(get_current_user),
    repository: AlertRepository = Depends(_alert_repository),
) -> PushKeyResponse:
    repository.set_user_pushover_key_encrypted(current_user.id, None)
    return PushKeyResponse(key_configured=False)


@router.get("/push-status", response_model=PushStatusResponse)
def get_push_status(settings: Settings = Depends(_push_settings)) -> PushStatusResponse:
    configured = bool(
        settings.push_notifications_enabled
        and settings.pushover_app_token
        and settings.pushover_key_encryption_key
    )
    return PushStatusResponse(configured=configured)


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
