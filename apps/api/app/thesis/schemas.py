"""Phase 19 (Part 3): the StockThesis read-model. Every field here is either
a verbatim embedding of an already-computed schema (MarketStructureSnapshot,
DecisionPlan, EvidenceDiffSnapshot, SetupCandidate, SetupCatalystContext,
AnalogQueryResponse -- all frozen elsewhere) or a small, deterministic,
documented derivation over those fields (research_lean, history_sufficiency,
contradictions). Nothing here is LLM-derived, scored, or predictive -- see
app.thesis.service for how each field is built.

"The user is 15." No BUY/SELL/STRONG BUY/STRONG SELL language, no 0-100
score, no invented confidence/win-probability/expected-return field exists
anywhere on this schema.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.api.routes.research_intelligence import AnalogQueryResponse
from app.decision_engine.schemas import DecisionPlan, EvidenceDiffSnapshot
from app.market_structure.schemas import TrendClass, TrendStrength
from app.news.schemas import CatalystEvent, SetupCatalystContext
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupCandidate
from app.support_resistance.schemas import LevelKind


class HistorySufficiency(str, Enum):
    """Deterministic label over how much genuine trading history backs this
    thesis -- never a substitute value for a pre-IPO/newly-listed symbol
    (Part 5). See app.thesis.service._history_sufficiency for the exact,
    documented candle_count thresholds."""

    FULL = "full"
    ADEQUATE = "adequate"
    LIMITED = "limited"
    VERY_LIMITED = "very_limited"
    INSUFFICIENT = "insufficient"


class ResearchLean(str, Enum):
    """(Part 3) Deterministic, never LLM-derived, never a numeric score.
    Conservative by construction: conflicting evidence -> MIXED, no usable
    evidence -> INSUFFICIENT_EVIDENCE, an ABSTAIN DecisionPlan -> ABSTAIN.
    Never BUY/SELL language."""

    BULLISH_LEAN = "bullish_lean"
    BEARISH_LEAN = "bearish_lean"
    MIXED = "mixed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ABSTAIN = "abstain"


class TimeframeTrendSummary(BaseModel):
    """One row of the multi-timeframe trend table (Part 3/6). `explanation`
    is copied verbatim from MarketStructureSnapshot.trend.evidence -- the
    same deterministic, template-built evidence strings the structure engine
    already produces, never regenerated or paraphrased here."""

    model_config = ConfigDict(frozen=True)

    timeframe: Timeframe
    trend: TrendClass
    strength: Optional[TrendStrength] = None
    explanation: list[str] = []
    candle_count: int = 0


class KeyLevelSummary(BaseModel):
    """One support/resistance zone, reduced to display fields. Provenance
    (`source_count`/`timeframes`) traces back to SupportResistanceSnapshot's
    own ConfluenceInfo -- never a freshly invented number."""

    model_config = ConfigDict(frozen=True)

    kind: LevelKind
    price: float
    is_nearest: bool = False
    source_count: int = 0
    timeframe_count: int = 0
    timeframes: list[Timeframe] = []


class SignalValidationSummary(BaseModel):
    """(Part 3/13) The current SIGNAL VALIDATION GATE state -- the exact
    same global, cross-symbol gate app.validation.gate evaluates, surfaced
    here read-only (never recomputed per thesis request; see
    app.thesis.service for why). Deliberately distinct from, and never
    combined with, the Forecast Lab's own Forward Validation Gate."""

    model_config = ConfigDict(frozen=True)

    gate_version: Optional[str] = None
    decision: str = "not_enough_data"
    reasons: list[str] = []
    evaluated_at: Optional[datetime] = None


class StockThesis(BaseModel):
    """(Phase 19, Part 3) The complete, composed, point-in-time research
    surface for one symbol -- bull case, bear case, trend, evidence, risk,
    catalyst context, and current research conclusion. Built entirely by
    composing already-computed, already-tested engine outputs (see
    app.thesis.service.build_stock_thesis); nothing on this schema is
    independently computed here."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    as_of: datetime
    generated_at: datetime

    market_data_provider: str
    market_data_cutoff: Optional[datetime] = None
    current_price: Optional[float] = None
    session: Optional[str] = None

    multi_timeframe_trend: list[TimeframeTrendSummary] = []
    key_levels: list[KeyLevelSummary] = []

    decision_plan: Optional[DecisionPlan] = None
    evidence_diffs: list[EvidenceDiffSnapshot] = []

    active_setups: list[SetupCandidate] = []
    near_misses: list[SetupCandidate] = []

    evidence_for: list[str] = []
    evidence_against: list[str] = []
    contradictions: list[str] = []

    catalyst_context: Optional[SetupCatalystContext] = None
    nearest_catalyst_event: Optional[CatalystEvent] = None

    historical_analogs: Optional[AnalogQueryResponse] = None

    signal_validation: SignalValidationSummary
    ranking_gate_status: str
    ranking_validation_message: str

    history_sufficiency: HistorySufficiency
    history_sufficiency_reason: str

    research_lean: ResearchLean
    research_lean_reasons: list[str] = []

    strengthens_if: list[str] = []
    weakens_if: list[str] = []
    invalidation: list[str] = []

    fundamentals_status: str = "FUNDAMENTAL ANALYSIS -- data source not configured"

    data_limitations: list[str] = []
