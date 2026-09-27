"""Phase 16 (§48/§52/§106): server-side entitlement enforcement.

`require_entitlement(feature)` ALWAYS re-derives the plan from the
authenticated user's own DB row (via get_current_user, itself resolved
only from a validated session token) -- never from a client-supplied
plan/entitlement claim in a header, query param, or request body. A
frontend that hides a button is not enforcement (§52); this dependency is.

No real billing provider (e.g. Stripe) is wired in this phase -- `plan` is
set only via the dev/admin-only plan-change endpoint below, and defaults
to "free" for every new signup. This is intentionally disclosed as
TEST-MODE-ONLY billing-ready architecture, not a live payment integration
(see the Phase 16 final report).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.billing.entitlements import plan_has_entitlement
from app.database.models import User


def require_entitlement(feature: str):
    def _check(current_user: User = Depends(get_current_user)) -> User:
        if not plan_has_entitlement(current_user.plan, feature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your current plan does not include '{feature}'. Upgrade to access this feature.",
            )
        return current_user

    return _check
