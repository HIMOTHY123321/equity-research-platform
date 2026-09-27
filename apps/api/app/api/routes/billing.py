"""Phase 16 (§48-§52/§106): billing-ready entitlement scaffold.

TEST-MODE ONLY -- there is no real payment provider wired here. `plan` is
set only via `POST /api/admin/users/{user_id}/plan` (admin-only, itself
gated on the caller's own server-side `role` column, never a client
claim) -- see the Phase 16 final report for what a real Stripe (or
similar) integration would still require before any real money moves.

`/api/billing/premium-example` exists purely to prove the enforcement
mechanism end-to-end (and is exercised by tests) -- no other route in this
codebase currently depends on `require_entitlement`, so gating an already-
shipped, currently-unauthenticated feature (e.g. the Validation Lab's AI
summary) behind login is a deliberately deferred, disclosed next step: the
frontend has no login/signup UI yet, and stranding an already-working
feature behind a login screen that doesn't exist would be a worse outcome
than leaving it open a little longer.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user, get_user_repository, require_admin
from app.auth.repository import UserRepository
from app.billing.dependencies import require_entitlement
from app.billing.entitlements import PLAN_ENTITLEMENTS, VALID_PLANS
from app.database.models import User

router = APIRouter(tags=["billing"])


class PlanOut(BaseModel):
    plan: str
    entitlements: list[str]


class SetPlanRequest(BaseModel):
    plan: str


@router.get("/api/billing/plan", response_model=PlanOut)
def get_my_plan(current_user: User = Depends(get_current_user)) -> PlanOut:
    return PlanOut(
        plan=current_user.plan, entitlements=sorted(PLAN_ENTITLEMENTS.get(current_user.plan, []))
    )


@router.get("/api/billing/premium-example")
def premium_example(
    current_user: User = Depends(require_entitlement("ai_validation_summary")),
) -> dict:
    return {"message": f"Hello {current_user.email}, your plan includes this feature."}


@router.post("/api/admin/users/{user_id}/plan", response_model=PlanOut)
def set_user_plan(
    user_id: str,
    payload: SetPlanRequest,
    _admin: User = Depends(require_admin),
    user_repository: UserRepository = Depends(get_user_repository),
) -> PlanOut:
    if payload.plan not in VALID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown plan {payload.plan!r}; expected one of {sorted(VALID_PLANS)}",
        )
    try:
        target = user_repository.get_by_id(UUID(user_id))
    except ValueError:
        target = None
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    updated = user_repository.update_plan(target, payload.plan)
    return PlanOut(plan=updated.plan, entitlements=sorted(PLAN_ENTITLEMENTS.get(updated.plan, [])))
