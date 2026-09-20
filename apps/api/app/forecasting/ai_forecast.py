"""Phase 12 (#D): the AI-synthesis forecast origin. Deliberately minimal --
this is a validation lab, not a place to deepen AI involvement. A provider
selects among the *same* closed forecast-value enums the deterministic
engine uses; nothing it returns is trusted until independently validated
the same way app.ai_analysis.validation grounds a ResearchBrief (evidence
refs must resolve within the supplied claims, banned language is rejected).
Any failure -- an invented value, an unresolvable ref, banned language, or
the provider being unavailable -- abstains. It never falls back to
pretending the deterministic engine's pick was "AI-selected".

This intentionally does not touch app.ai_analysis.provider.AIAnalysisProvider
(the shared ResearchBrief-synthesis ABC): forecasting builds on top of
app.ai_analysis's EvidencePacket, so a forecast-selection capability defined
there would be a layering inversion. This is its own, narrower ABC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.ai_analysis.claims import EvidenceClaim
from app.ai_analysis.schemas import EvidencePacket
from app.ai_analysis.validation import _BANNED_PATTERNS
from app.forecasting.config import DEFAULT_FORECAST_CONFIG, ForecastConfig
from app.forecasting.deterministic import ForecastDecision, generate_deterministic_forecast
from app.forecasting.evidence_quality import classify_evidence_quality
from app.forecasting.schemas import (
    FORECAST_VALUES_BY_CATEGORY,
    AbstentionReason,
    ForecastCategory,
)


class ForecastSelectionUnavailable(RuntimeError):
    """Raised by a ForecastSelectionProvider when it cannot produce a
    selection (no credentials, provider error) -- the caller abstains."""


@dataclass(frozen=True)
class RawForecastSelection:
    forecast_value: str
    evidence_refs: list[str]
    rationale: str


class ForecastSelectionProvider(ABC):
    name: str

    @abstractmethod
    def select(
        self,
        packet: EvidencePacket,
        claims: list[EvidenceClaim],
        category: ForecastCategory,
        allowed_values: frozenset[str],
    ) -> RawForecastSelection: ...


class MockForecastSelectionProvider(ForecastSelectionProvider):
    """Deterministic by construction: mirrors app.forecasting.deterministic
    exactly, so its output is trivially grounded (never fails validation).
    Used as the default and by every test -- demonstrates the full AI-
    synthesis pipeline (selection -> validation -> ledger) without claiming
    any actual model involvement."""

    name = "mock"

    def select(self, packet, claims, category, allowed_values) -> RawForecastSelection:
        decision = generate_deterministic_forecast(packet, category)
        if decision.abstained:
            raise ForecastSelectionUnavailable(decision.rationale)
        return RawForecastSelection(
            forecast_value=decision.forecast_value,
            evidence_refs=decision.evidence_refs,
            rationale=decision.rationale,
        )


def _valid_refs(claims: list[EvidenceClaim]) -> set[str]:
    refs: set[str] = set()
    for claim in claims:
        refs.update(claim.evidence_refs)
    return refs


def _contains_banned_language(text: str) -> bool:
    return any(pattern.search(text) for _code, pattern in _BANNED_PATTERNS)


def select_ai_forecast(
    packet: EvidencePacket,
    claims: list[EvidenceClaim],
    category: ForecastCategory,
    provider: ForecastSelectionProvider,
    config: ForecastConfig = DEFAULT_FORECAST_CONFIG,
) -> ForecastDecision:
    quality = classify_evidence_quality(packet, config)
    allowed_values = FORECAST_VALUES_BY_CATEGORY[category]

    try:
        raw = provider.select(packet, claims, category, allowed_values)
    except ForecastSelectionUnavailable as exc:
        return ForecastDecision(
            forecast_value=None,
            evidence_quality=quality,
            rationale=str(exc),
            abstention_reason=AbstentionReason.PROVIDER_LIMITATION,
        )

    valid_refs = _valid_refs(claims)
    if raw.forecast_value not in allowed_values:
        return ForecastDecision(
            forecast_value=None,
            evidence_quality=quality,
            rationale=f"Provider selected {raw.forecast_value!r}, not a valid {category.value} state.",
            abstention_reason=AbstentionReason.PROVIDER_LIMITATION,
        )
    if not raw.evidence_refs or any(ref not in valid_refs for ref in raw.evidence_refs):
        return ForecastDecision(
            forecast_value=None,
            evidence_quality=quality,
            rationale="Provider cited an evidence reference that does not resolve within the "
            "supplied claims.",
            abstention_reason=AbstentionReason.PROVIDER_LIMITATION,
        )
    if _contains_banned_language(raw.rationale):
        return ForecastDecision(
            forecast_value=None,
            evidence_quality=quality,
            rationale="Provider rationale contained banned language and was rejected.",
            abstention_reason=AbstentionReason.PROVIDER_LIMITATION,
        )

    return ForecastDecision(
        forecast_value=raw.forecast_value,
        evidence_quality=quality,
        evidence_refs=raw.evidence_refs,
        rationale=raw.rationale,
    )
