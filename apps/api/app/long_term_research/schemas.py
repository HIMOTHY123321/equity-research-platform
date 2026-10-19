"""Long-Term Investing Research domain schemas -- a feature wholly
separate from app.decision_engine's short/medium-term setup tracking (see
that module's own DecisionState, which this module never imports or
reuses: a long-term "accumulation candidate" is never derived from a
short-term "ENTRY CONDITIONS MET").

This module defines only vocabulary and plain data shapes. All actual
computation lives in app.long_term_research.factors (fundamentals/price
series -> factor states) and app.long_term_research.rules (factor states
-> LongTermResearchState) -- both pure functions, never randomized, never
dependent on hidden state.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LongTermResearchState(str, Enum):
    """The only eight closed-enum outcomes this feature can ever produce.
    Deliberately NOT a 0-100 score, and deliberately never the literal
    words BUY/STRONG BUY/SELL/STRONG SELL (see
    app.decision_engine.ai_brief.contains_banned_language, reused as-is
    by app.long_term_research.push for the same guarantee)."""

    ACCUMULATION_CANDIDATE = "ACCUMULATION_CANDIDATE"
    WATCH_FOR_BETTER_ENTRY = "WATCH_FOR_BETTER_ENTRY"
    HOLDING_THESIS_INTACT = "HOLDING_THESIS_INTACT"
    LONG_TERM_THESIS_STRENGTHENING = "LONG_TERM_THESIS_STRENGTHENING"
    LONG_TERM_THESIS_WEAKENING = "LONG_TERM_THESIS_WEAKENING"
    REVIEW_POSITION = "REVIEW_POSITION"
    THESIS_INVALIDATED = "THESIS_INVALIDATED"
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"


PUSH_WORTHY_STATES = frozenset(
    {
        LongTermResearchState.ACCUMULATION_CANDIDATE,
        LongTermResearchState.LONG_TERM_THESIS_STRENGTHENING,
        LongTermResearchState.LONG_TERM_THESIS_WEAKENING,
        LongTermResearchState.REVIEW_POSITION,
        LongTermResearchState.THESIS_INVALIDATED,
    }
)
"""Per spec: a push is sent only when a symbol's state TRANSITIONS into
one of these (never merely because it currently IS one of these -- see
app.long_term_research.service's transition-detection, which compares
against the most recent PRIOR snapshot, not a fixed "is it bad" check)."""


class BusinessQualityState(str, Enum):
    STRONG = "STRONG"
    STABLE = "STABLE"
    WEAK = "WEAK"
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"


class EarningsTrendState(str, Enum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    WEAKENING = "WEAKENING"
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"


class ValuationState(str, Enum):
    CHEAP = "CHEAP"
    REASONABLE = "REASONABLE"
    EXPENSIVE = "EXPENSIVE"
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"


class GrowthState(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"


class LongTermTrendState(str, Enum):
    CONSTRUCTIVE = "CONSTRUCTIVE"
    NEUTRAL = "NEUTRAL"
    WEAKENING = "WEAKENING"
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"


class LongTermEvidenceQuality(str, Enum):
    """Mirrors the naming spirit of app.forecasting.schemas.
    EvidenceQualityState (HIGH_EVIDENCE_SUPPORT/MIXED_EVIDENCE/
    WEAK_EVIDENCE/INSUFFICIENT_EVIDENCE) without importing it directly --
    that enum is specific to forecast-horizon evidence, this one to
    long-term factor coverage; keeping them separate avoids silently
    coupling two different grading systems that happen to look similar."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"


class FundamentalsSnapshot(BaseModel):
    """Whatever a FundamentalsProvider genuinely returned for this symbol
    as of `fetched_at` -- every field Optional because real-world
    coverage varies enormously (a brand-new SPAC/IPO legitimately has
    almost none of these yet). Never fabricated when missing -- see
    app.long_term_research.fundamentals, whose docstring discloses
    exactly which yfinance fields back each one and their known
    limitations."""

    symbol: str
    fetched_at: datetime
    provider: str
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    price_to_sales: Optional[float] = None
    profit_margin: Optional[float] = None
    return_on_equity: Optional[float] = None
    debt_to_equity: Optional[float] = None
    free_cash_flow: Optional[float] = None
    quarterly_revenue: list[float] = Field(default_factory=list)
    """Oldest -> newest, one entry per reported quarter. Only quarters
    the provider actually returned a numeric value for -- never
    interpolated or back-filled."""
    quarterly_eps: list[float] = Field(default_factory=list)
    """Oldest -> newest, same convention as quarterly_revenue."""
    market_cap: Optional[float] = None


class LongTermFactorEvidence(BaseModel):
    """One factor's own positive/negative/missing reasons, in plain
    English, produced by the SAME function that set that factor's state
    (app.long_term_research.factors) -- never invented downstream.
    LongTermResearchResult's own evidence lists are simply the
    concatenation of every factor's lists here."""

    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class LongTermFactorBundle(BaseModel):
    business_quality: BusinessQualityState
    business_quality_evidence: LongTermFactorEvidence
    earnings_trend: EarningsTrendState
    earnings_trend_evidence: LongTermFactorEvidence
    valuation: ValuationState
    valuation_evidence: LongTermFactorEvidence
    growth: GrowthState
    growth_evidence: LongTermFactorEvidence
    long_term_trend: LongTermTrendState
    long_term_trend_evidence: LongTermFactorEvidence
    history_days: int
    """Calendar days between the earliest candle used and `as_of` --
    the raw measurement `limited_history` below is derived from."""
    limited_history: bool
    """True when `history_days` is below
    app.long_term_research.factors.LIMITED_HISTORY_DAYS_THRESHOLD (e.g.
    a recent IPO/SPAC like SPCX) -- per spec, this must be explicitly
    labeled rather than silently producing confident-looking output; it
    lowers evidence_quality's ceiling in app.long_term_research.rules."""
    accumulation_area_low: Optional[float] = None
    accumulation_area_high: Optional[float] = None
    invalidation_level: Optional[float] = None


class LongTermResearchResult(BaseModel):
    """One deterministic daily research conclusion for one symbol as of
    one instant -- the frozen, persisted unit (see
    app.long_term_research.repository). `ai_summary`, when present, is
    pure plain-English rendering of the fields below, generated strictly
    AFTER `research_state` is already fixed by app.long_term_research.
    rules -- nothing downstream of that point can read `ai_summary` and
    feed back into `research_state` (see app.long_term_research.summary's
    own docstring and the structural test proving this invariant)."""

    symbol: str
    as_of: datetime
    price: Optional[float]
    research_state: LongTermResearchState
    factors: LongTermFactorBundle
    evidence_quality: LongTermEvidenceQuality
    positive_evidence: list[str]
    negative_evidence: list[str]
    contradictions: list[str]
    missing_evidence: list[str]
    reason: str
    what_would_change_state: str
    market_data_provider: str
    fundamentals_provider: str
    pipeline_version: str = "ltr-v1"
    ai_summary: Optional[str] = None
