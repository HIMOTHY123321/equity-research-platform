"""Phase 11 (#C): provider-independent AI analysis abstraction. Same shape
as app.market_data.provider.MarketDataProvider / app.news.provider.NewsProvider
-- an ABC, one or more concrete implementations, and a single settings-based
selection point (app.api.deps.get_ai_analysis_provider). Nothing else in the
codebase should import a concrete provider class directly.

Every method receives only an EvidencePacket and its derived EvidenceClaims
-- never raw database/provider access, never future candles, never
unrestricted tool use (#D). A provider may fail (timeout, missing
credentials, malformed response); callers must treat that as "AI section
unavailable," never as a reason the deterministic evidence disappears (#C).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.ai_analysis.claims import EvidenceClaim
from app.ai_analysis.research_brief import AnalysisMode, ResearchBrief
from app.ai_analysis.schemas import EvidencePacket


class AIAnalysisUnavailableError(RuntimeError):
    """Raised by a provider when it cannot produce an analysis (no
    credentials, provider error, timeout) -- callers catch this and continue
    rendering deterministic evidence with an explicit "AI unavailable"
    state, never a failed request (#C)."""


class AIAnalysisProvider(ABC):
    name: str

    @abstractmethod
    def explain_setup(self, packet: EvidencePacket, claims: list[EvidenceClaim]) -> str:
        """Short prose answering "why was this setup detected?", grounded
        strictly in `claims`."""

    @abstractmethod
    def summarize_contradictions(self, packet: EvidencePacket, claims: list[EvidenceClaim]) -> str:
        """Short prose answering "what does the historical data NOT prove?",
        grounded strictly in CONTRADICTING/UNKNOWN-direction claims."""

    @abstractmethod
    def generate_monitoring_summary(
        self, packet: EvidencePacket, claims: list[EvidenceClaim]
    ) -> list[str]:
        """Prose explanations of the deterministic invalidation/monitoring
        conditions already on `packet.setup.candidate.invalidation_criteria`
        (#G) -- never invents new conditions or price targets."""

    @abstractmethod
    def synthesize_research_brief(
        self, packet: EvidencePacket, claims: list[EvidenceClaim], mode: AnalysisMode
    ) -> ResearchBrief:
        """The single entry point every analysis mode (#F) calls through.
        Must return a `ResearchBrief` whose `evidence_refs` are a subset of
        `claims`' own refs -- app.ai_analysis.validation independently
        re-checks this before the result is ever served or persisted."""
