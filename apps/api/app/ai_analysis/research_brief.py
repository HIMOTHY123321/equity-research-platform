"""Phase 11 (#D/#F/#J): the structured output an AIAnalysisProvider must
produce, and the fixed set of explanation modes every provider supports.
`ResearchBrief` is what gets validated (app.ai_analysis.validation) and
persisted (app.ai_analysis.repository) -- never freeform chat text.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

RESEARCH_BRIEF_PROMPT_VERSION = "v1"


class AnalysisMode(str, Enum):
    """(#F) All six modes read the same EvidencePacket/claims; only which
    ResearchBrief sections are populated and which prompt template variant
    is used differs. Never a different data source per mode."""

    QUICK = "quick"
    FULL = "full"
    WHY_THIS_SETUP = "why_this_setup"
    WHY_NOT = "why_not"
    CATALYST = "catalyst"
    ANALOGS = "analogs"


class ResearchBrief(BaseModel):
    """(#D) Grounded, structured synthesis output. `evidence_refs` on each
    section must be a subset of the refs already present on the
    EvidenceClaims the provider was given (app.ai_analysis.validation
    enforces this) -- a brief never introduces a citation the deterministic
    claims layer didn't already produce."""

    model_config = ConfigDict(frozen=True)

    brief_id: str
    evidence_packet_id: str
    mode: AnalysisMode

    situation_summary: str = ""
    setup_explanation: str = ""
    supporting_evidence: list[str] = []
    contradictory_evidence: list[str] = []
    catalyst_context: str = ""
    historical_context: str = ""
    uncertainty: list[str] = []
    invalidation_conditions: list[str] = []
    monitor_next: list[str] = []
    evidence_refs: list[str] = []

    generated_at: datetime
    as_of: datetime
    provider: str
    model: Optional[str] = None
    prompt_version: str = RESEARCH_BRIEF_PROMPT_VERSION

    # Set only when validation rejected the provider's raw output and this
    # brief was assembled from deterministic claims alone (#D "reject or
    # sanitize"). Never populated by a provider itself.
    grounding_rejected: bool = False
    grounding_violations: list[str] = []
