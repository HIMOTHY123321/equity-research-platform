"""The cross-symbol Decision Scanner (§9/§36/§37/§38): a deterministic
summary of the Decision Engine's current state across the whole monitoring
universe, urgency/category sorted -- explicitly NOT a numerical ranking or
"best trade" score. Reuses DecisionEngineRepository verbatim; this module
only aggregates and sorts what already exists, adding no new evaluation
logic (§6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.alerts.schemas import DEFAULT_SEVERITY_BY_ALERT_TYPE, AlertSeverity
from app.alerts.service import TRANSITION_ALERT_TYPE_BY_STATE
from app.decision_engine.repository import DecisionEngineRepository
from app.decision_engine.schemas import DecisionPlan, DecisionState
from app.market_structure.schemas import Direction
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupType

# Lower rank = surfaced first. Derived from the same severity table the
# alert system uses (never a second, independently-tuned urgency scale) --
# ABSTAIN and "no plan at all" sink to the very bottom, matching §9's
# "CRITICAL changes -> IMPORTANT -> active thesis -> WATCHING ->
# ABSTAIN/no plan" ordering.
_SEVERITY_RANK = {
    AlertSeverity.CRITICAL: 0,
    AlertSeverity.IMPORTANT: 1,
    AlertSeverity.NOTICE: 2,
    AlertSeverity.INFO: 3,
}
_NO_PLAN_RANK = 5
_ABSTAIN_RANK = 4


def _urgency_rank(state: Optional[DecisionState]) -> int:
    if state is None:
        return _NO_PLAN_RANK
    if state == DecisionState.ABSTAIN:
        return _ABSTAIN_RANK
    alert_type = TRANSITION_ALERT_TYPE_BY_STATE.get(state)
    if alert_type is None:
        return _ABSTAIN_RANK
    return _SEVERITY_RANK[DEFAULT_SEVERITY_BY_ALERT_TYPE[alert_type]]


def _most_urgent_plan(plans: list[DecisionPlan]) -> Optional[DecisionPlan]:
    """The single plan to surface for a symbol. ABSTAIN plans ARE eligible
    here (unlike `other_monitored_plan_count`, which excludes them) --
    a symbol whose only plan(s) abstained must show state=ABSTAIN, not be
    indistinguishable from a symbol with no plan at all (§9)."""
    if not plans:
        return None
    return min(plans, key=lambda p: (_urgency_rank(p.state), -p.as_of.timestamp()))


class ScannerRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    decision_plan_id: Optional[str] = None
    state: Optional[DecisionState] = None
    """None means no DecisionPlan exists yet for this symbol at all --
    distinct from ABSTAIN, which means a setup was found and explicitly
    abstained on."""
    setup_type: Optional[SetupType] = None
    timeframe: Optional[Timeframe] = None
    direction: Optional[Direction] = None
    research_status: list[str] = []
    ranking_gate_status: str = "fail"
    last_change_at: Optional[datetime] = None
    other_monitored_plan_count: int = 0
    """§10: how many other open plans exist for this symbol beyond the one
    surfaced above -- never silently overwritten, never hidden."""


def build_scanner_rows(symbols: list[str], repository: DecisionEngineRepository) -> list[ScannerRow]:
    rows: list[ScannerRow] = []
    for symbol in symbols:
        plans = repository.list_plans(symbol=symbol, limit=1000)
        primary = _most_urgent_plan(plans)
        if primary is None:
            rows.append(ScannerRow(symbol=symbol))
            continue
        other_open = [
            p
            for p in plans
            if p.decision_plan_id != primary.decision_plan_id and p.state != DecisionState.ABSTAIN
        ]
        rows.append(
            ScannerRow(
                symbol=symbol,
                decision_plan_id=primary.decision_plan_id,
                state=primary.state,
                setup_type=primary.setup_type,
                timeframe=primary.timeframe,
                direction=primary.direction,
                research_status=[r.value for r in primary.research_status],
                ranking_gate_status=primary.ranking_gate_status,
                last_change_at=primary.as_of,
                other_monitored_plan_count=len(other_open),
            )
        )
    rows.sort(key=lambda r: (_urgency_rank(r.state), r.symbol))
    return rows
