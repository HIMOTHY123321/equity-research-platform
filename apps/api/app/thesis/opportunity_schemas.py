"""Phase 19 (Part 2): the OpportunityCandidate read-model. Deliberately no
score field anywhere -- attention categories reuse the exact Decision
Engine state vocabulary (app.decision_engine.schemas.DecisionState) rather
than inventing a ranking language, and `why` is a deterministic sentence
built only from fields already on the candidate, never an LLM guess.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.decision_engine.schemas import DecisionState
from app.market_structure.schemas import TrendClass
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import Direction, SetupType
from app.thesis.schemas import HistorySufficiency


class AttentionCategory(str, Enum):
    """(Part 2) Reuses Decision-state terminology verbatim wherever a
    DecisionPlan exists; NEAR_SETUP and INSUFFICIENT_DATA are the only two
    labels that describe a symbol with no open DecisionPlan yet."""

    ENTRY_CONDITIONS_MET = "entry_conditions_met"
    ACTIVE_THESIS = "active_thesis"
    THESIS_STRENGTHENING = "thesis_strengthening"
    WATCHING = "watching"
    NEAR_SETUP = "near_setup"
    MIXED = "mixed"
    ABSTAIN = "abstain"
    INSUFFICIENT_DATA = "insufficient_data"


class OpportunityCandidate(BaseModel):
    """One symbol's current, factual research standing -- never a
    predictive score. `why` is deterministic and traceable to the other
    fields on this same object."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: datetime
    timeframe: Timeframe

    category: AttentionCategory
    decision_state: Optional[DecisionState] = None
    why: str

    setup_type: Optional[SetupType] = None
    direction: Optional[Direction] = None
    structure_trend: Optional[TrendClass] = None

    contradictions_present: bool = False
    signal_validation_decision: str = "not_enough_data"
    ranking_gate_status: str = "fail"

    market_data_provider: str
    # None for symbols already backed by an open DecisionPlan -- computing
    # this precisely would require an extra, otherwise-unnecessary
    # market_snapshot fetch per row (Part 11); see GET /api/symbols/
    # {symbol}/thesis for the precise, single-symbol value instead.
    history_sufficiency: Optional[HistorySufficiency] = None

    monitored: bool = True

    decision_plan_id: Optional[str] = None


class OpportunityListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    timeframe: Timeframe
    candidates: list[OpportunityCandidate]
    ranking_validation_message: str
