"""Prospective outcome integration (§33/§34, hardened §Phase-14.1-4): which
AlertEvents are eligible to eventually feed Forward Validation, and the
mechanical guarantee that dev fixtures/historical replay/synthetic test
events can never inflate that count.

This module does NOT compute outcomes (1/3/5/10/20-bar returns, MFE, MAE,
time-to-invalidation/exit/excursion) -- see app.alerts.resolver for that.
What IS in scope, and load-bearing: every AlertEvent already carries
exactly the references the resolver needs (`decision_plan_id`,
`transition_id`, `occurred_at`, `evaluated_at`, `symbol`, `timeframe`), and
this module is the one place that decides which rows are even candidates.

Phase 14.1 hardening: `origin` alone is a caller-supplied field on a
pydantic model -- nothing stops a bug (or a test) from constructing an
AlertEvent with `origin=live_prospective` that was actually produced by the
dev-fixture code path. `is_prospective_eligible` therefore does NOT trust
`origin` alone; it additionally verifies PROVENANCE that the caller cannot
simply set on the AlertEvent object:

  1. `origin == live_prospective` (necessary, not sufficient).
  2. `symbol` is not one of the fixed, structurally-reserved fixture
     symbols (ZFXA/ZFXB/ZFXC -- see app.decision_engine.fixtures; these can
     never collide with a real ticker by construction of the ticker
     validator, so this check costs nothing and cannot false-positive on
     genuine market data).
  3. A DecisionPlan with `decision_plan_id` actually exists in the
     DecisionEngineRepository (the durable, independently-written record of
     what the Decision Engine really did) -- an alert whose plan was never
     persisted (e.g. a synthetic/in-memory-only test event) is rejected.
  4. That persisted plan's `setup_id` does not carry the `"fixture:"` prefix
     every dev-fixture-built plan is stamped with in
     app.decision_engine.fixtures.build_fixture_plan -- independent of
     whatever origin the alert claims.
  5. If the alert carries a `transition_id`, a matching DecisionTransition
     actually exists in that plan's persisted transition history.

All five must agree for an alert to be prospectively eligible.
"""

from __future__ import annotations

from app.alerts.schemas import AlertEvent, AlertOrigin, AlertType
from app.decision_engine.repository import DecisionEngineRepository

# ENTRY/STRENGTHENING/WEAKENING/EXIT/INVALIDATED per §33 -- the five
# transition families with a genuine forward-looking outcome to measure.
# PLAN_CREATED/WATCHING/EXPIRED/CONDITION_*/CONFLICT_*/CATALYST_*/DATA_*/
# STREAM_* have no bar-return-style outcome to resolve and are never
# eligible regardless of origin.
PROSPECTIVE_ELIGIBLE_ALERT_TYPES = frozenset(
    {
        AlertType.ENTRY_CONDITIONS_MET,
        AlertType.THESIS_STRENGTHENING,
        AlertType.THESIS_WEAKENING,
        AlertType.EXIT_CONDITIONS_MET,
        AlertType.INVALIDATED,
    }
)

# Kept as a plain literal set (not an import from app.decision_engine.
# fixtures) so this eligibility check never depends on that dev-only
# module's scenario list changing shape -- these three symbols are a
# structural, load-bearing contract (app.schemas.symbols.TICKER_PATTERN
# guarantees no real ticker can ever collide with them), not merely
# whatever fixtures.py happens to define today.
_RESERVED_FIXTURE_SYMBOLS = frozenset({"ZFXA", "ZFXB", "ZFXC"})

_FIXTURE_SETUP_ID_PREFIX = "fixture:"


def is_prospective_eligible(alert: AlertEvent, decision_repository: DecisionEngineRepository) -> bool:
    """Provenance-derived eligibility (§Phase-14.1-4) -- never trusts
    `alert.origin` alone. `decision_repository` is the independent source
    of truth an alert's claimed provenance is checked against."""
    if alert.origin != AlertOrigin.LIVE_PROSPECTIVE:
        return False
    if alert.alert_type not in PROSPECTIVE_ELIGIBLE_ALERT_TYPES:
        return False
    if alert.symbol in _RESERVED_FIXTURE_SYMBOLS:
        return False
    if alert.decision_plan_id is None:
        return False

    plan = decision_repository.get_plan(alert.decision_plan_id)
    if plan is None:
        return False
    if plan.setup_id.startswith(_FIXTURE_SETUP_ID_PREFIX):
        return False

    if alert.transition_id is not None:
        transitions = decision_repository.list_transitions(alert.decision_plan_id)
        if not any(t.transition_id == alert.transition_id for t in transitions):
            return False

    return True
