"""Typed Decision Engine outputs.

Mirrors the conventions established in app.setup_detection.schemas
(SetupCandidate): one unified, immutable record per DecisionPlan, a
`state` + `transitions` lifecycle (never a bare boolean), and typed
`DecisionCondition` facts rather than free-text. A DecisionPlan freezes the
rules that existed when monitoring began -- see DecisionPlan's docstring for
why nothing on an open plan is ever retroactively rewritten.

No BUY/SELL/confidence-percentage/score language is modeled anywhere in this
package -- see docs on RANKING GATE. Only the state names below are used to
describe a plan's status.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.market_structure.schemas import Direction
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupType


class DecisionState(str, Enum):
    DETECTED = "detected"
    EVALUATING = "evaluating"
    ABSTAIN = "abstain"
    WATCHING = "watching"
    ENTRY_CONDITIONS_MET = "entry_conditions_met"
    ACTIVE_THESIS = "active_thesis"
    THESIS_STRENGTHENING = "thesis_strengthening"
    THESIS_WEAKENING = "thesis_weakening"
    INVALIDATED = "invalidated"
    EXIT_CONDITIONS_MET = "exit_conditions_met"
    EXPIRED = "expired"


# States after which a DecisionPlan no longer evaluates new conditions or
# transitions further -- the terminal states of the lifecycle.
TERMINAL_STATES = frozenset(
    {
        DecisionState.ABSTAIN,
        DecisionState.INVALIDATED,
        DecisionState.EXIT_CONDITIONS_MET,
        DecisionState.EXPIRED,
    }
)


class AbstentionReason(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    WEAK_EVIDENCE = "weak_evidence"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    NO_VALID_SETUP = "no_valid_setup"
    STALE_DATA = "stale_data"
    UNSUPPORTED_TIMEFRAME = "unsupported_timeframe"
    RESEARCH_GATE_FAILURE = "research_gate_failure"
    MISSING_MARKET_DATA = "missing_market_data"


class ConditionType(str, Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    CLOSE_ABOVE = "close_above"
    CLOSE_BELOW = "close_below"
    LEVEL_HOLD = "level_hold"
    LEVEL_RECLAIM = "level_reclaim"
    LEVEL_REJECTION = "level_rejection"
    BREAKOUT_CONFIRMED = "breakout_confirmed"
    RETEST_CONFIRMED = "retest_confirmed"
    STRUCTURE_BOS = "structure_bos"
    STRUCTURE_CHOCH = "structure_choch"
    TREND_ALIGNMENT = "trend_alignment"
    RVOL_ABOVE = "rvol_above"
    RVOL_BELOW = "rvol_below"
    VOLUME_CONFIRMATION = "volume_confirmation"
    SUPPORT_HOLDS = "support_holds"
    RESISTANCE_HOLDS = "resistance_holds"
    GAP_FILL_THRESHOLD = "gap_fill_threshold"
    GAP_HOLD_THRESHOLD = "gap_hold_threshold"
    VOLATILITY_REGIME = "volatility_regime"
    CATALYST_PRESENT = "catalyst_present"
    CATALYST_ABSENT = "catalyst_absent"
    TIME_ELAPSED = "time_elapsed"
    SESSION_CONDITION = "session_condition"


class ConditionRole(str, Enum):
    """A single typed condition can serve more than one purpose on a plan --
    role says which list(s) it belongs to (entry / invalidation / exit /
    monitoring), never inferred from position in a list."""

    ENTRY = "entry"
    INVALIDATION = "invalidation"
    EXIT = "exit"
    MONITORING = "monitoring"


class ConditionOperator(str, Enum):
    GTE = ">="
    LTE = "<="
    GT = ">"
    LT = "<"
    EQ = "=="
    PRESENT = "present"
    ABSENT = "absent"


class ConditionStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class BarSemantics(str, Enum):
    """What kind of market event a condition is legally allowed to evaluate
    against (#17 of the Phase 13 spec). A `close_above` condition on a 5m
    level MUST NOT become true from an intrabar wick -- only from a
    COMPLETED_BAR of that exact timeframe. TICK conditions may use live
    trade/quote events where the underlying data source supports them."""

    TICK = "tick"
    FORMING_BAR = "forming_bar"
    COMPLETED_BAR = "completed_bar"


class DecisionCondition(BaseModel):
    """One deterministic, typed fact -- never free text. `timeframe` is what
    makes cross-timeframe conditions representable (a 5m entry trigger next
    to a 1H/1D structure condition) without ever losing which timeframe a
    given fact was evaluated on."""

    model_config = ConfigDict(frozen=True)

    id: str
    role: ConditionRole
    type: ConditionType
    description: str
    timeframe: Timeframe
    bar_semantics: BarSemantics
    operator: ConditionOperator
    required_value: Optional[float] = None
    actual_value: Optional[float] = None
    status: ConditionStatus
    evaluated_at: Optional[datetime] = None
    source_evidence_ref: Optional[str] = None


class DecisionTransition(BaseModel):
    """Append-only ledger entry. Never deleted or edited once created -- the
    full lifecycle of a DecisionPlan must remain auditable (see repository.py,
    which exposes no update/delete for transitions)."""

    model_config = ConfigDict(frozen=True)

    transition_id: str
    decision_plan_id: str
    from_state: Optional[DecisionState]
    to_state: DecisionState
    occurred_at: datetime
    as_of: datetime
    reason: str
    trigger_condition_ids: list[str] = []
    evidence_refs: list[str] = []
    pipeline_version: str


class ActivationSnapshot(BaseModel):
    """Frozen the instant a plan enters ACTIVE_THESIS. Every later
    strengthening/weakening/invalidation judgement diffs the *current*
    deterministic evidence against exactly this snapshot -- never a
    recomputed or retroactively adjusted baseline."""

    model_config = ConfigDict(frozen=True)

    activated_at: datetime
    activation_price_reference: Optional[float] = None
    structure_by_timeframe: dict[str, str] = {}
    nearest_support_price: Optional[float] = None
    nearest_resistance_price: Optional[float] = None
    rvol: Optional[float] = None
    atr: Optional[float] = None
    catalyst_label: Optional[str] = None
    invalidation_distance: Optional[float] = None
    evidence_packet_id: Optional[str] = None
    forecast_refs: list[str] = []


class FieldChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    from_value: Optional[str] = None
    to_value: Optional[str] = None


class ThesisDirectionClass(str, Enum):
    STRENGTHENING = "strengthening"
    WEAKENING = "weakening"
    NEUTRAL = "neutral"


class EvidenceDiffSnapshot(BaseModel):
    """One point-in-time comparison of the activation snapshot against a
    later evaluation. No AI interpretation is required to produce this --
    it is a deterministic field-by-field diff (#8 of the Phase 13 spec)."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    decision_plan_id: str
    as_of: datetime
    changes: list[FieldChange]
    classification: ThesisDirectionClass
    classification_reasons: list[str]


class ResearchStatusLabel(str, Enum):
    """Prominently surfaced when the Research Gate / Ranking Gate do not
    justify stronger language -- a plan may still be monitored for research
    purposes while explicitly labeled this way (#15 of the Phase 13 spec)."""

    RESEARCH_MONITORING_ONLY = "research_monitoring_only"
    INSUFFICIENT_FOR_RANKED_SIGNAL = "insufficient_for_ranked_signal"


class DecisionPlan(BaseModel):
    """Immutable except for `state`/`transitions`/`activation_snapshot`,
    which only ever move forward through state_machine.transition(). A plan
    freezes the entry/invalidation/exit/monitoring condition thresholds that
    existed when monitoring began -- later market data, however favorable,
    never rewrites them. To change the rules, a new DecisionPlan is created;
    the old one is never mutated in place."""

    model_config = ConfigDict(frozen=True)

    decision_plan_id: str
    symbol: str
    timeframe: Timeframe
    setup_id: str
    setup_type: SetupType
    direction: Direction

    created_at: datetime
    as_of: datetime
    state: DecisionState

    entry_conditions: list[DecisionCondition]
    invalidation_conditions: list[DecisionCondition]
    exit_conditions: list[DecisionCondition]
    monitoring_conditions: list[DecisionCondition]

    transitions: list[DecisionTransition]
    activation_snapshot: Optional[ActivationSnapshot] = None

    research_status: list[ResearchStatusLabel] = []
    evidence_quality: Optional[str] = None
    ranking_gate_status: str = "fail"

    abstention_reason: Optional[AbstentionReason] = None

    source_setup_snapshot_id: Optional[str] = None
    source_evidence_packet_id: Optional[str] = None

    pipeline_version: str
    schema_version: str = "1.0"
