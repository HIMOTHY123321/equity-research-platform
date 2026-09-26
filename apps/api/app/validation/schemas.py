"""Phase 15: schemas for prospective validation & signal qualification.

`ProspectiveObservation` is a read-model projection, not a new source of
truth -- it is assembled at query time from already-persisted
`AlertEvent`/`AlertOutcome`/`DecisionPlan` rows (app.validation.dataset),
the same way app.research_intelligence.evidence_card assembles
`ResearchEvidenceCard` from `SetupLedgerEntry`/`SetupOutcomeRecord` without
duplicating that data into a new table.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ResolutionQuality(str, Enum):
    """Per Phase 15 §3: never silently convert missing future data to
    zero. `INSUFFICIENT_FUTURE_DATA` is the normal, expected state for a
    recently-created alert -- not an error."""

    VALID = "valid"
    PARTIAL = "partial"
    INSUFFICIENT_FUTURE_DATA = "insufficient_future_data"
    DATA_GAP = "data_gap"
    STALE_SOURCE = "stale_source"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class DatasetOrigin(str, Enum):
    """Which dataset an observation came from -- historical and
    prospective results must never be silently mixed (§1/§23)."""

    PROSPECTIVE = "prospective"
    HISTORICAL_REPLAY = "historical_replay"


class ProspectiveObservation(BaseModel):
    """One prospective (genuine, live-monitored) Decision/Alert
    observation, projected from persisted data for research purposes
    only. Never itself persisted as a new source-of-truth row."""

    model_config = ConfigDict(frozen=True)

    observation_id: str
    alert_id: str
    decision_plan_id: Optional[str] = None
    transition_id: Optional[str] = None

    symbol: str
    setup_type: Optional[str] = None
    direction: Optional[str] = None
    timeframe: Optional[str] = None

    decision_state: Optional[str] = None
    event_type: str

    detected_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    alert_occurred_at: datetime
    resolved_at: Optional[datetime] = None

    reference_price: Optional[float] = None
    reference_bar_timestamp: Optional[datetime] = None

    return_1: Optional[float] = None
    return_3: Optional[float] = None
    return_5: Optional[float] = None
    return_10: Optional[float] = None
    return_20: Optional[float] = None

    mfe_atr: Optional[float] = None
    mae_atr: Optional[float] = None
    time_to_mfe: Optional[int] = None
    time_to_mae: Optional[int] = None
    time_to_invalidation: Optional[int] = None
    time_to_exit: Optional[int] = None

    market_regime: Optional[str] = None
    volatility_regime: Optional[str] = None
    session: Optional[str] = None
    catalyst_classification: Optional[str] = None

    research_status_at_event: list[str] = []
    ranking_gate_status_at_event: Optional[str] = None

    provider: Optional[str] = None
    source_timestamp: Optional[datetime] = None

    origin: DatasetOrigin
    schema_version: str = "1.0"
    pipeline_version: str

    resolved: bool = False
    resolution_quality: ResolutionQuality = ResolutionQuality.INSUFFICIENT_FUTURE_DATA


class BaselineType(str, Enum):
    UNCONDITIONAL = "unconditional"
    MATCHED_REGIME = "matched_regime"
    REJECTED_CANDIDATE = "rejected_candidate"
    DETECTION = "detection"
    TIME_MATCHED = "time_matched"


class ReplicationStatus(str, Enum):
    """Rule-based only (§24) -- never AI-assigned."""

    NOT_ENOUGH_DATA = "not_enough_data"
    EARLY_SIGNAL = "early_signal"
    MIXED = "mixed"
    NOT_REPLICATED = "not_replicated"
    REPLICATED = "replicated"
    DEGRADED = "degraded"
    CONTRADICTED = "contradicted"


class QualificationState(str, Enum):
    INSUFFICIENT = "insufficient"
    PROMISING = "promising"
    MIXED = "mixed"
    FAILED = "failed"
    QUALIFIED = "qualified"


class ConcentrationWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    dominant_value: str
    share: float
    warning: str


class CostSensitivityPoint(BaseModel):
    """ESTIMATED COST SENSITIVITY -- a research haircut applied to
    already-observed returns, never an actual fill simulation (§14)."""

    model_config = ConfigDict(frozen=True)

    cost_bps: float
    median_return_after_cost: Optional[float] = None
    mean_return_after_cost: Optional[float] = None
    positive_rate_after_cost: Optional[float] = None


class CohortStatistics(BaseModel):
    model_config = ConfigDict(frozen=True)

    cohort_label: str
    horizon_bars: int

    raw_n: int
    independent_n: int
    purged_n: int

    mean: Optional[float] = None
    median: Optional[float] = None
    stdev: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    positive_rate: Optional[float] = None

    mfe_atr_median: Optional[float] = None
    mae_atr_median: Optional[float] = None

    invalidation_rate: Optional[float] = None
    exit_rate: Optional[float] = None

    bootstrap_available: bool = False
    bootstrap_point_estimate: Optional[float] = None
    bootstrap_lower: Optional[float] = None
    bootstrap_upper: Optional[float] = None
    bootstrap_method: Optional[str] = None

    baseline_type: Optional[BaselineType] = None
    baseline_median: Optional[float] = None
    effect_vs_baseline: Optional[float] = None

    cost_sensitivity: list[CostSensitivityPoint] = []
    concentration_warnings: list[ConcentrationWarning] = []


class HistoricalProspectiveComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    cohort_label: str
    historical_n: int
    historical_median_effect: Optional[float] = None
    prospective_n: int
    prospective_median_effect: Optional[float] = None
    direction_agreement: Optional[bool] = None
    magnitude_agreement: Optional[bool] = None
    note: Optional[str] = None
