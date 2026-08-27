"""Typed setup-detection outputs.

The central design decision this package makes (see the ADR for the full
rationale): detection and qualification are two different things, and both
are preserved on one unified `SetupCandidate` record rather than two. A
candidate that never qualifies isn't discarded -- its `hard_checks` show
exactly which required condition failed, which is the backbone of the
"why not?" engine (#5). `current_state` plus `transitions` is the lifecycle
(#3); nothing is ever modeled as a bare boolean.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.market_structure.schemas import Direction, TrendClass
from app.schemas.market_data import Timeframe


class SetupType(str, Enum):
    PREVIOUS_DAY_HIGH_BREAKOUT = "previous_day_high_breakout"
    PREVIOUS_DAY_LOW_BREAKDOWN = "previous_day_low_breakdown"
    PREVIOUS_WEEK_HIGH_BREAKOUT = "previous_week_high_breakout"
    PREVIOUS_WEEK_LOW_BREAKDOWN = "previous_week_low_breakdown"
    BREAKOUT_RETEST = "breakout_retest"
    WICK_FAILED_BREAKOUT = "wick_failed_breakout"
    CONFIRMED_BREAKOUT_FAILURE = "confirmed_breakout_failure"
    SUPPORT_RECLAIM = "support_reclaim"
    RESISTANCE_REJECTION = "resistance_rejection"
    GAP_CONTINUATION = "gap_continuation"
    GAP_FILL = "gap_fill"
    BULLISH_LIQUIDITY_SWEEP = "bullish_liquidity_sweep"
    BEARISH_LIQUIDITY_SWEEP = "bearish_liquidity_sweep"
    MOVING_AVERAGE_RECLAIM = "moving_average_reclaim"
    TREND_PULLBACK = "trend_pullback"
    RANGE_BREAKOUT = "range_breakout"


class SetupLifecycleState(str, Enum):
    CANDIDATE = "candidate"
    QUALIFIED = "qualified"
    TRIGGERED = "triggered"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    REJECTED = "rejected"


class RuleType(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class ConflictSeverity(str, Enum):
    MAJOR = "major"
    MINOR = "minor"


class BreakoutConfirmation(str, Enum):
    """Separate, never-conflated concepts (#7): a wick beyond a level is not
    a breakout; only a completed close beyond it is."""

    WICK_BREACH = "wick_breach"
    CLOSE_BREAK = "close_break"


class SetupDetectionStatus(str, Enum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


class EvidenceCheck(BaseModel):
    """One deterministic, structured fact -- never bare prose. `label` is a
    short f-string built directly from `actual`/`required`, not generated
    text, same convention as TrendClassification.evidence elsewhere."""

    model_config = ConfigDict(frozen=True)

    code: str
    label: str
    rule_type: RuleType
    passed: bool
    actual: Optional[float] = None
    required: Optional[float] = None
    source: str


class ConflictCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    label: str
    severity: ConflictSeverity
    actual: Optional[float] = None
    reference: Optional[float] = None
    source: str


class LifecycleTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: SetupLifecycleState
    timestamp: datetime
    reason_code: str
    reason_label: str


class MarketContext(BaseModel):
    """Architecture placeholder for #28 -- deliberately unpopulated in
    Phase 6 (see config.benchmark_symbol / ADR 0007). Present so later
    phases can add SPY/QQQ-relative context without a schema migration."""

    model_config = ConfigDict(frozen=True)

    benchmark_symbol: str
    trend: Optional[TrendClass] = None
    as_of: datetime


class SetupContext(BaseModel):
    """A frozen reference snapshot of the deterministic conditions that
    existed when a candidate was actually detected (#18) -- never
    recomputed later from newer data."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime
    daily_structure: Optional[TrendClass] = None
    four_hour_structure: Optional[TrendClass] = None
    one_hour_structure: Optional[TrendClass] = None
    atr: Optional[float] = None
    rvol: Optional[float] = None
    ema20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    active_range_high: Optional[float] = None
    active_range_low: Optional[float] = None
    gap_percent: Optional[float] = None
    gap_direction: Optional[str] = None
    nearest_support_price: Optional[float] = None
    nearest_resistance_price: Optional[float] = None
    market_context: Optional[MarketContext] = None


class SetupFingerprint(BaseModel):
    """Standardized categorical/numeric features (#19) for a future analog
    search -- buckets, never raw floats, so fingerprints are comparable
    across symbols. No historical performance is attached in Phase 6."""

    model_config = ConfigDict(frozen=True)

    setup_type: SetupType
    direction: Direction
    daily_structure: Optional[TrendClass] = None
    four_hour_structure: Optional[TrendClass] = None
    one_hour_structure: Optional[TrendClass] = None
    rvol_bucket: Optional[str] = None
    gap_state: str = "none"
    distance_to_weekly_resistance_bucket: Optional[str] = None
    distance_to_weekly_support_bucket: Optional[str] = None
    support_confluence: int = 0
    resistance_confluence: int = 0


class SetupCandidate(BaseModel):
    """The one unified record type for every stage of a setup's life --
    candidate, qualified, triggered, invalidated, expired, and rejected all
    use this same shape, distinguished by `current_state`. Nothing about a
    rejected candidate is ever discarded (#4)."""

    model_config = ConfigDict(frozen=True)

    id: str
    symbol: str
    timeframe: Timeframe
    setup_type: SetupType
    direction: Direction

    reference_price: Optional[float] = None
    reference_source: Optional[str] = None
    reference_timestamp: Optional[datetime] = None
    confirmation: Optional[BreakoutConfirmation] = None

    candidate_candle_timestamp: datetime
    created_at: datetime
    current_state: SetupLifecycleState
    transitions: list[LifecycleTransition]

    hard_checks: list[EvidenceCheck]
    soft_checks: list[EvidenceCheck]
    conflicts: list[ConflictCheck]

    # Deterministic, template-built statements of what would invalidate this
    # specific pattern (#30) -- never freeform/generated text.
    invalidation_criteria: list[str] = []

    context: Optional[SetupContext] = None
    fingerprint: Optional[SetupFingerprint] = None

    expires_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    invalidation_reason: Optional[str] = None
    triggered_at: Optional[datetime] = None

    metadata: dict = {}


class SetupDetectionDataQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: SetupDetectionStatus
    source_timeframe: Timeframe
    candles_consumed: int
    detectors_run: int
    detectors_skipped: list[str] = []
    warnings: list[str] = []


class SetupDetectionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    as_of: datetime

    qualified_setups: list[SetupCandidate]
    candidates: list[SetupCandidate]
    rejected_candidates: list[SetupCandidate]
    recently_invalidated: list[SetupCandidate]
    recently_expired: list[SetupCandidate]

    data_quality: SetupDetectionDataQuality
