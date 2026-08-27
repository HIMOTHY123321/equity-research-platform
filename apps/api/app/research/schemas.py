"""Typed research outputs. The module boundary IS the detection/evaluation
boundary (#2): nothing in this file's `SetupOutcome` tree is ever consulted
by app.setup_detection, and nothing here is computed without candles
strictly after the setup's own detection instant.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.setup_detection.schemas import SetupCandidate


class ResearchRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SampleSizeLabel(str, Enum):
    INSUFFICIENT = "insufficient_sample"
    SMALL = "small_sample"
    MODERATE = "moderate_sample"
    LARGER = "larger_sample"


class DatasetProvenance(BaseModel):
    """Item #8 -- enough metadata to know exactly which dataset produced a
    result, since yfinance data is not guaranteed immutable or revision-free."""

    model_config = ConfigDict(frozen=True)

    provider: str
    symbol: str
    timeframe: str
    requested_start: datetime
    requested_end: datetime
    earliest_candle: Optional[datetime] = None
    latest_candle: Optional[datetime] = None
    candle_count: int
    adjustment_mode: str
    timezone: str
    data_hash: str


class HorizonOutcome(BaseModel):
    """One forward-looking horizon (#9, #17). `available=False` means fewer
    than `horizon_bars` future completed candles exist yet -- never
    fabricated, never silently omitted."""

    model_config = ConfigDict(frozen=True)

    horizon_bars: int
    available: bool
    future_close: Optional[float] = None
    absolute_change: Optional[float] = None
    raw_return_percent: Optional[float] = None
    directional_return_percent: Optional[float] = None


class ExcursionMetrics(BaseModel):
    """MFE or MAE (#11/#12). `absolute`/`percent`/`atr` are already
    direction-adjusted -- MFE is always >= 0, MAE is always <= 0, in the
    same convention as `directional_return_percent`. `atr` uses the ATR
    frozen in the setup's own detection-time context, never a future value."""

    model_config = ConfigDict(frozen=True)

    absolute: Optional[float] = None
    percent: Optional[float] = None
    atr: Optional[float] = None
    bars_until: Optional[int] = None
    timestamp: Optional[datetime] = None


class StructuralEventOutcome(BaseModel):
    """One objectively-defined descriptive research label (#15) -- never a
    trading target."""

    model_config = ConfigDict(frozen=True)

    code: str
    occurred: bool
    timestamp: Optional[datetime] = None
    bars_until: Optional[int] = None


class EvaluationQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    bars_available_after_detection: int
    fully_evaluated: bool
    warnings: list[str] = []


class SetupOutcome(BaseModel):
    """The complete evaluation-time record for one setup (#16). Deliberately
    a separate top-level object from SetupCandidate -- nothing in this
    class is ever read back into detection logic."""

    model_config = ConfigDict(frozen=True)

    setup_id: str
    base_price: float
    detection_atr: Optional[float] = None
    evaluation_start: datetime
    evaluation_end: Optional[datetime] = None

    horizons: list[HorizonOutcome]
    mfe: ExcursionMetrics
    mae: ExcursionMetrics
    structural_events: list[StructuralEventOutcome] = []
    evaluation_quality: EvaluationQuality


class SetupLedgerEntry(BaseModel):
    """The append-only-in-spirit ledger record (#5). `detection` is frozen
    at first observation and never recomputed; `latest` reflects whatever
    lifecycle state replay has observed most recently for the same
    deterministic setup id."""

    model_config = ConfigDict(frozen=True)

    research_run_id: str
    setup_id: str
    symbol: str
    timeframe: str
    setup_type: str
    direction: str
    first_seen_at: datetime
    candidate_candle_timestamp: datetime
    detection: SetupCandidate
    current_state: str
    last_observed_at: datetime
    latest: SetupCandidate
    outcome: Optional[SetupOutcome] = None


class HorizonStat(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon_bars: int
    n: int
    mean: Optional[float] = None
    median: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None


class GroupOutcomeStats(BaseModel):
    """Descriptive statistics for one group (qualified, rejected, a specific
    rejection code, a baseline bucket, ...) at every horizon (#35/#36)."""

    model_config = ConfigDict(frozen=True)

    sample_count: int
    sample_size_label: SampleSizeLabel
    directional_return_by_horizon: list[HorizonStat]
    mfe_atr: Optional[HorizonStat] = None
    mae_atr: Optional[HorizonStat] = None


class QualificationLift(BaseModel):
    """Observed historical difference between qualified and rejected
    candidates of the same setup type (#38) -- explicitly NOT causal."""

    model_config = ConfigDict(frozen=True)

    horizon_bars: int
    qualified_median: Optional[float] = None
    rejected_median: Optional[float] = None
    observed_difference: Optional[float] = None


class RejectionValueEntry(BaseModel):
    """Descriptive comparison for one rejection reason code (#39)."""

    model_config = ConfigDict(frozen=True)

    rejection_code: str
    sample_count: int
    sample_size_label: SampleSizeLabel
    median_5bar_directional_return: Optional[float] = None
    comparable_qualified_median_5bar_directional_return: Optional[float] = None


class BaselineComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    unconditional: GroupOutcomeStats
    regime_matched: Optional[GroupOutcomeStats] = None
    regime_label: Optional[str] = None


class SetupTypeSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    setup_type: str
    qualified: GroupOutcomeStats
    rejected: GroupOutcomeStats
    qualification_lift: list[QualificationLift]
    rejection_value: list[RejectionValueEntry]
    baseline: Optional[BaselineComparison] = None


class ResearchRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    bars_processed: int
    qualified_count: int
    rejected_count: int
    runtime_seconds: float
    setup_types: list[SetupTypeSummary]
