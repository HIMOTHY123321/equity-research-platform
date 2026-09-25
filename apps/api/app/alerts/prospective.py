"""Prospective outcome integration (§33/§34): which AlertEvents are
eligible to eventually feed Forward Validation, and the mechanical
guarantee that dev fixtures/historical replay can never inflate that count.

This module does NOT compute outcomes (1/3/5/10/20-bar returns, MFE, MAE,
time-to-invalidation/exit/excursion) -- that is a genuine future-data
resolver in the same shape as app.forecasting.resolver.resolve_forecast,
deliberately out of scope here. What IS in scope, and load-bearing today:
every AlertEvent already carries exactly the references such a resolver
would need (`decision_plan_id`, `transition_id`, `occurred_at`,
`evaluated_at`, `symbol`, `timeframe`) -- nothing else needs to be stored
now to make that resolver possible later, and this module is the one place
that decides which rows are even candidates, so a future resolver (or this
one, once written) never has to re-derive that policy.

Only `AlertOrigin.LIVE_PROSPECTIVE` alerts of the eligible types are ever
candidates. `dev_fixture` and `historical_replay` are never eligible, full
stop -- not filtered out at query time by a caller who might forget, but
made structurally impossible to count by routing every count through
`is_prospective_eligible`."""

from __future__ import annotations

from app.alerts.schemas import AlertEvent, AlertOrigin, AlertType

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


def is_prospective_eligible(alert: AlertEvent) -> bool:
    return (
        alert.origin == AlertOrigin.LIVE_PROSPECTIVE
        and alert.alert_type in PROSPECTIVE_ELIGIBLE_ALERT_TYPES
    )
