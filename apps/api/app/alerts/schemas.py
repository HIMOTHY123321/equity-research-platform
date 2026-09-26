"""Typed AlertEvent model (Phase 14).

An AlertEvent is a deterministic, immutable record of ONE meaningful change
already produced by the Decision Engine (a state transition, a condition
flipping PASSED/FAILED, a conflict appearing/disappearing, a catalyst
reclassification, or a data-freshness/stream-health change) -- never a
prediction, never a score, never generated because "an LLM decided
something looks important" (see app.decision_engine.ai_brief for the
equivalent, pre-existing discipline this package copies).

`origin` is the mechanical enforcement behind "dev fixtures/historical
replay never count as real monitoring history" (§35/§52 of the Phase 14
spec) -- the exact same closed-enum idiom app.forecasting.schemas
.ForecastRunMode already uses to separate PROSPECTIVE from BACKTEST_REPLAY;
every query that feeds the Alert Center, unread counts, or Forward
Validation eligibility filters on this field.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

ALERT_SCHEMA_VERSION = "1.0"


class AlertType(str, Enum):
    PLAN_CREATED = "plan_created"
    WATCHING = "watching"
    ENTRY_CONDITIONS_MET = "entry_conditions_met"
    THESIS_ACTIVATED = "thesis_activated"
    THESIS_STRENGTHENING = "thesis_strengthening"
    THESIS_WEAKENING = "thesis_weakening"
    INVALIDATED = "invalidated"
    EXIT_CONDITIONS_MET = "exit_conditions_met"
    EXPIRED = "expired"

    CONDITION_PASSED = "condition_passed"
    CONDITION_FAILED = "condition_failed"

    CONFLICT_ADDED = "conflict_added"
    CONFLICT_REMOVED = "conflict_removed"

    CATALYST_UPDATE = "catalyst_update"

    DATA_STALE = "data_stale"
    DATA_RECOVERED = "data_recovered"

    STREAM_DISCONNECTED = "stream_disconnected"
    STREAM_RECONNECTED = "stream_reconnected"


# The state-transition alert types, in the exact order state_machine.py's
# TRANSITION_TABLE allows them to occur -- used both for severity lookup and
# for the "this AlertType corresponds 1:1 to a DecisionTransition" contract
# dedup.py relies on.
_TRANSITION_ALERT_TYPES = frozenset(
    {
        AlertType.WATCHING,
        AlertType.ENTRY_CONDITIONS_MET,
        AlertType.THESIS_ACTIVATED,
        AlertType.THESIS_STRENGTHENING,
        AlertType.THESIS_WEAKENING,
        AlertType.INVALIDATED,
        AlertType.EXIT_CONDITIONS_MET,
        AlertType.EXPIRED,
    }
)


class AlertSeverity(str, Enum):
    """Urgency -- "how soon should the user look at this" -- never a
    prediction of outcome likelihood. No percentages, no scores anywhere
    near this enum."""

    INFO = "info"
    NOTICE = "notice"
    IMPORTANT = "important"
    CRITICAL = "critical"


# Deterministic, fixed severity per alert type (§4 of the spec). Plan
# creation/entry conditions rate higher than passive monitoring noise;
# invalidation is always the strongest signal a thesis is over.
DEFAULT_SEVERITY_BY_ALERT_TYPE: dict[AlertType, AlertSeverity] = {
    AlertType.PLAN_CREATED: AlertSeverity.INFO,
    AlertType.WATCHING: AlertSeverity.INFO,
    AlertType.ENTRY_CONDITIONS_MET: AlertSeverity.IMPORTANT,
    AlertType.THESIS_ACTIVATED: AlertSeverity.IMPORTANT,
    AlertType.THESIS_STRENGTHENING: AlertSeverity.NOTICE,
    AlertType.THESIS_WEAKENING: AlertSeverity.IMPORTANT,
    AlertType.INVALIDATED: AlertSeverity.CRITICAL,
    AlertType.EXIT_CONDITIONS_MET: AlertSeverity.IMPORTANT,
    AlertType.EXPIRED: AlertSeverity.NOTICE,
    AlertType.CONDITION_PASSED: AlertSeverity.NOTICE,
    AlertType.CONDITION_FAILED: AlertSeverity.NOTICE,
    AlertType.CONFLICT_ADDED: AlertSeverity.NOTICE,
    AlertType.CONFLICT_REMOVED: AlertSeverity.NOTICE,
    AlertType.CATALYST_UPDATE: AlertSeverity.INFO,
    AlertType.DATA_STALE: AlertSeverity.IMPORTANT,
    AlertType.DATA_RECOVERED: AlertSeverity.INFO,
    AlertType.STREAM_DISCONNECTED: AlertSeverity.IMPORTANT,
    AlertType.STREAM_RECONNECTED: AlertSeverity.INFO,
}


class AlertOrigin(str, Enum):
    """(§35/§52) The ONLY field that determines whether an alert is real
    monitoring history. Mirrors app.forecasting.schemas.ForecastRunMode's
    PROSPECTIVE/BACKTEST_REPLAY split exactly -- every query behind the
    Alert Center, unread counts, and Forward Validation eligibility filters
    on this field with the same plain list-comprehension idiom
    app.forecasting.gate already uses (`f.run_mode.value == "prospective"`)."""

    LIVE_PROSPECTIVE = "live_prospective"
    DEV_FIXTURE = "dev_fixture"
    HISTORICAL_REPLAY = "historical_replay"


class AlertEvent(BaseModel):
    """Immutable once created (§5). If something changes later, a NEW
    AlertEvent is created -- nothing here is ever rewritten in place."""

    model_config = ConfigDict(frozen=True)

    alert_id: str
    symbol: str
    decision_plan_id: Optional[str] = None
    setup_id: Optional[str] = None

    alert_type: AlertType
    severity: AlertSeverity
    title: str
    summary: str

    previous_state: Optional[str] = None
    current_state: Optional[str] = None

    occurred_at: datetime
    """The instant the underlying market/decision event actually happened
    (e.g. a DecisionTransition's own `occurred_at`) -- never the alert's own
    creation time. See §14."""
    source_timestamp: Optional[datetime] = None
    """The provider's own timestamp for the data that triggered this alert,
    when distinct from `occurred_at` (e.g. a delayed yfinance bar)."""
    evaluated_at: datetime
    """The as_of the deterministic evaluation used -- anti-lookahead proof
    point (§48): nothing after this instant could have influenced this
    alert."""

    trigger_condition_ids: list[str] = []
    evidence_refs: list[str] = []
    transition_id: Optional[str] = None

    timeframe: Optional[str] = None
    setup_type: Optional[str] = None
    direction: Optional[str] = None

    research_status: list[str] = []
    ranking_gate_status: str = "fail"
    forward_validation_gate_status: Optional[str] = None

    provider: Optional[str] = None
    data_freshness_state: Optional[str] = None

    dedup_key: str
    """Deterministic, computed by app.alerts.dedup -- never user-supplied.
    Enforced unique at the database layer (§47), the actual exactly-once
    mechanism, not merely an in-memory set."""
    origin: AlertOrigin
    schema_version: str = ALERT_SCHEMA_VERSION
    pipeline_version: str

    created_at: datetime
    """When this row was actually written -- distinct from `occurred_at`."""


class AlertAcknowledgement(BaseModel):
    """User read-state, stored separately from the immutable AlertEvent
    (§17) -- acknowledging an alert never mutates its market-event
    contents."""

    model_config = ConfigDict(frozen=True)

    alert_id: str
    acknowledged_at: datetime


class AlertPreference(BaseModel):
    """Per-category on/off toggle (§21). One row per alert_type; unset
    types fall back to DEFAULT_ALERT_PREFERENCES."""

    model_config = ConfigDict(frozen=True)

    alert_type: AlertType
    enabled: bool


# Deliberately not a blanket "alert on everything" default -- passive/
# expected states (WATCHING, THESIS_STRENGTHENING, EXPIRED) default off,
# the decisive ones (ENTRY/WEAKENING/INVALIDATED/EXIT) default on. The spec
# explicitly permits deviating from its own example defaults "if existing
# product conventions suggest better behavior"; this mirrors the severity
# table above (IMPORTANT/CRITICAL default on, INFO/NOTICE default off),
# which keeps the two concepts consistent with each other.
DEFAULT_ALERT_PREFERENCES: dict[AlertType, bool] = {
    AlertType.PLAN_CREATED: False,
    AlertType.WATCHING: False,
    AlertType.ENTRY_CONDITIONS_MET: True,
    AlertType.THESIS_ACTIVATED: True,
    AlertType.THESIS_STRENGTHENING: False,
    AlertType.THESIS_WEAKENING: True,
    AlertType.INVALIDATED: True,
    AlertType.EXIT_CONDITIONS_MET: True,
    AlertType.EXPIRED: False,
    AlertType.CONDITION_PASSED: False,
    AlertType.CONDITION_FAILED: False,
    AlertType.CONFLICT_ADDED: False,
    AlertType.CONFLICT_REMOVED: False,
    AlertType.CATALYST_UPDATE: False,
    AlertType.DATA_STALE: True,
    AlertType.DATA_RECOVERED: False,
    AlertType.STREAM_DISCONNECTED: True,
    AlertType.STREAM_RECONNECTED: False,
}


class MonitoringSubscription(BaseModel):
    """One symbol's monitoring configuration (§8/§22) -- deliberately
    separate from Watchlist membership: viewing a symbol is not the same as
    wanting alert delivery for it."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    enabled: bool
    preferred_timeframes: list[str] = []
    decision_monitoring_enabled: bool = True
    added_at: datetime


class AlertOutcome(BaseModel):
    """The resolved, future-data-informed outcome of one eligible
    prospective AlertEvent (§33, Phase 14.1). Produced ONLY by
    app.alerts.resolver -- the one place in this package allowed to look at
    candles after `alert.occurred_at` (same discipline as
    app.forecasting.resolver / app.research.outcomes). Never rewritten once
    created: a re-resolution attempt is a no-op (see
    AlertRepository.save_outcome's insert-or-ignore contract), enforced at
    the database layer via a UNIQUE constraint on `alert_id`, not merely by
    convention."""

    model_config = ConfigDict(frozen=True)

    outcome_id: str
    alert_id: str
    symbol: str
    decision_plan_id: Optional[str] = None

    resolved_at: datetime
    """When this outcome was computed -- distinct from `resolution_as_of`."""
    resolution_as_of: datetime
    """The latest real market instant this outcome's future-data lookups
    were truncated to -- the anti-lookahead proof point."""

    # 1/3/5/10/20-bar directional returns (None when that horizon's bars
    # aren't available yet -- never fabricated).
    return_1_bar_percent: Optional[float] = None
    return_3_bar_percent: Optional[float] = None
    return_5_bar_percent: Optional[float] = None
    return_10_bar_percent: Optional[float] = None
    return_20_bar_percent: Optional[float] = None

    mfe_atr: Optional[float] = None
    mfe_bars_until: Optional[int] = None
    mae_atr: Optional[float] = None
    mae_bars_until: Optional[int] = None

    bars_to_invalidation: Optional[int] = None
    """None if the plan never reached INVALIDATED within the resolved
    window -- never inferred, only read off an already-persisted, later
    INVALIDATED transition for the same decision_plan_id."""
    bars_to_exit: Optional[int] = None
    bars_to_favorable_excursion: Optional[int] = None
    """Alias of mfe_bars_until, kept as its own named field per §33's
    explicit "time to favorable excursion" requirement."""
    bars_to_adverse_excursion: Optional[int] = None

    schema_version: str = "1.0"
    pipeline_version: str


class AlertHorizonOutcome(BaseModel):
    """Phase 15: one independently-resolved horizon (1, 3, 5, 10, or 20
    bars) for one eligible prospective AlertEvent. Unlike AlertOutcome
    (which waits for all 20 bars before persisting anything), this
    resolves and persists the instant ITS OWN horizon's future bars exist
    -- a still-pending horizon simply has no row (see
    AlertRepository.get_horizon_outcomes_for_alert), never a fabricated
    value. Never rewritten once created: enforced via a UNIQUE constraint
    on (alert_id, horizon_bars), the same resolve-once discipline as
    AlertOutcome itself."""

    model_config = ConfigDict(frozen=True)

    outcome_id: str
    alert_id: str
    symbol: str
    decision_plan_id: Optional[str] = None
    horizon_bars: int

    resolved_at: datetime
    resolution_as_of: datetime
    """The latest real market instant this horizon's return was computed
    against -- the anti-lookahead proof point for this horizon alone."""

    return_percent: float

    schema_version: str = "1.0"
    pipeline_version: str
