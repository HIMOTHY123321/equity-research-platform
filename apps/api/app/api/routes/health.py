"""Phase 16 (§25/§26/§75/§76): health/readiness endpoints and honest
provider-status reporting.

/health/live -- process alive (never touches the DB or a provider; a
    load balancer uses this to decide whether to kill/restart the
    process, so it must never block on a slow dependency).
/health/ready -- can this replica actually serve traffic (DB reachable,
    required config present)? A temporarily degraded market-data provider
    does NOT fail readiness (§25: "do not make readiness fail merely
    because a third-party market provider temporarily has no tick") --
    only things that make EVERY request fail (no DB) do.
/api/system/status -- which market/news/AI providers are actually
    configured, and whether streaming is a genuine entitlement or just
    code that exists -- never fabricates a "licensed" claim, and never
    returns a credential/API key value.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Environment, get_settings
from app.database.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live")
def health_live() -> dict:
    return {"status": "alive"}


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    checks: dict[str, str] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 -- deliberate: report, never crash the health check itself
        if settings.environment == Environment.PRODUCTION:
            checks["database"] = "unavailable"
        else:
            checks["database"] = f"unavailable: {exc}"

    ready = checks["database"] == "ok"
    return {"status": "ready" if ready else "not_ready", "checks": checks}


@router.get("/api/system/status")
def system_status() -> dict:
    settings = get_settings()
    market_provider = settings.market_data_provider.lower()
    news_provider = settings.news_provider.lower()

    return {
        "environment": settings.environment,
        "worker_mode": settings.worker_mode,
        "market_data": {
            "provider": market_provider,
            # §35/§76: yfinance is a development/research fallback ONLY --
            # this field exists so a deployment can never claim licensed
            # real-time data while quietly running on it. Production
            # startup already refuses to boot with market_data_provider=
            # yfinance (see app.config's production validator) -- this is
            # the honest runtime confirmation of that same fact.
            "is_licensed_commercial_feed": market_provider not in ("yfinance", "fixture"),
            "development_only_fallback_in_use": market_provider == "yfinance",
        },
        "news": {
            "provider": news_provider,
            "development_only_fallback_in_use": news_provider in ("yfinance", "fixture"),
        },
        "ai_analysis": {
            "provider": settings.ai_analysis_provider.lower(),
        },
    }
