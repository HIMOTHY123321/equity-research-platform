"""Phase 16 (§47/§48/§49): plan -> feature entitlement mapping.

`PLAN_ENTITLEMENTS` is the single source of truth for what a plan
unlocks; enforcement always happens server-side (app.billing.dependencies
.require_entitlement), never trusted from a client-supplied plan/role
header or field (§106/§107).

Explicitly never gated by plan (§49) -- these are safety/integrity
information, not premium convenience features: data freshness, provider
provenance, research warnings/concentration warnings, invalidation state,
the Signal Validation Gate and Ranking Gate results themselves. Nothing in
this module or its callers may add such a field to a plan's feature set.
"""

from __future__ import annotations

FREE = "free"
PRO = "pro"

#: Test-mode-only plan tiers. No real billing provider is wired to these
#: (see the module docstring in app.billing.dependencies) -- a plan value
#: here is set only via the dev/admin plan-change endpoint, never through
#: a real payment.
PLAN_ENTITLEMENTS: dict[str, frozenset[str]] = {
    FREE: frozenset(),
    PRO: frozenset({"ai_validation_summary"}),
}

VALID_PLANS = frozenset(PLAN_ENTITLEMENTS.keys())


def plan_has_entitlement(plan: str, feature: str) -> bool:
    return feature in PLAN_ENTITLEMENTS.get(plan, frozenset())
