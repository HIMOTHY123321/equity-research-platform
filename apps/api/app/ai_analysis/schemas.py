"""Phase 11 (#A): the deterministic, immutable EvidencePacket -- the single
object an AI provider is ever allowed to see. Every field here is either a
verbatim embedding of an already-computed, already-tested Phase 1-10.1
schema (never re-derived) or plain identity/provenance metadata. Nothing in
this module computes a statistic; app.ai_analysis.evidence_packet composes
these fields by calling the existing engines.

`ranking_gate_status` is a static constant, not a per-query measurement: it
records the binding Phase 9 architectural decision (ADR 0012, RANKING GATE =
FAIL) so every packet is self-describing about that constraint without this
phase silently reopening it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.api.routes.research_catalysts import CatalystResearchQueryResponse
from app.api.routes.research_intelligence import AnalogQueryResponse
from app.features.schemas import FeatureSnapshot
from app.market_structure.schemas import MarketStructureSnapshot
from app.news.schemas import CatalystEvent, SetupCatalystContext
from app.setup_detection.schemas import SetupCandidate
from app.support_resistance.schemas import SupportResistanceSnapshot

EVIDENCE_PACKET_SCHEMA_VERSION = "1.0"

# ADR 0012's binding decision -- Phase 11 does not revisit it. Embedded on
# every packet as a plain, non-computed constant so a downstream AI provider
# (and its human reader) always sees this boundary alongside the evidence,
# never has to look it up separately.
RANKING_GATE_STATUS = "FAIL"


class EvidenceSetupSection(BaseModel):
    """The target setup candidate plus deterministic, template-built
    explanations of why it qualified/was rejected -- reusing
    `SetupCandidate.hard_checks`/`soft_checks`/`conflicts`/
    `invalidation_criteria` verbatim (Phase 6, #4/#18/#30), never
    regenerating that text."""

    model_config = ConfigDict(frozen=True)

    candidate: SetupCandidate
    qualified: bool
    qualification_reasons: list[str] = []
    rejection_reasons: list[str] = []
    near_miss_reasons: list[str] = []
    conflict_reasons: list[str] = []


class EvidenceDataQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    missing_evidence: list[str] = []
    stale_evidence: list[str] = []
    insufficient_history: bool = False
    provider_limitations: list[str] = []
    research_limitations: list[str] = []


class EvidenceProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    market_data_provider: str
    news_provider: Optional[str] = None
    research_run_ids: list[str] = []
    analog_corpus_run_ids: list[str] = []
    generated_at: datetime


class EvidencePacket(BaseModel):
    """(#A) The complete, immutable, as_of-bound evidence surface for one
    symbol/timeframe, optionally scoped to one setup candidate. Composed
    entirely from Phase 1-10.1 outputs; see app.ai_analysis.evidence_packet
    for how each section is assembled and app/ai_analysis/../tests for the
    anti-lookahead determinism proof (#A closing requirement)."""

    model_config = ConfigDict(frozen=True)

    packet_id: str
    schema_version: str = EVIDENCE_PACKET_SCHEMA_VERSION
    as_of: datetime
    generated_at: datetime
    symbol: str
    timeframe: str
    session: Optional[str] = None
    current_price: Optional[float] = None

    setup: Optional[EvidenceSetupSection] = None

    structure: MarketStructureSnapshot
    multi_timeframe_structure: dict[str, MarketStructureSnapshot] = {}
    support_resistance: SupportResistanceSnapshot
    features: FeatureSnapshot

    historical_research: Optional[CatalystResearchQueryResponse] = None
    historical_analogs: Optional[AnalogQueryResponse] = None

    catalyst_context: Optional[SetupCatalystContext] = None
    nearest_catalyst_event: Optional[CatalystEvent] = None

    ranking_gate_status: str = RANKING_GATE_STATUS
    data_quality: EvidenceDataQuality
    provenance: EvidenceProvenance
