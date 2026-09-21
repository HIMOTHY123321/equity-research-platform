"""Phase 12 (#B/#C/#D): rule-based forecast generation, or an honest
abstention. Every rule below reads only already-computed EvidencePacket
fields (never re-derives a statistic) and ties its hypothesis to a real,
already-qualified/detected deterministic signal -- a DIRECTION or
STRUCTURE forecast is never a bare guess, it is the setup's own already-
validated directional thesis, tested against a further horizon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.ai_analysis.schemas import EvidencePacket
from app.forecasting.config import DEFAULT_FORECAST_CONFIG, ForecastConfig
from app.forecasting.evidence_quality import classify_evidence_quality
from app.forecasting.schemas import (
    AbstentionReason,
    CatalystReactionForecastValue,
    DirectionForecastValue,
    EvidenceQualityState,
    ForecastCategory,
    SetupOutcomeForecastValue,
    StructureForecastValue,
    VolatilityForecastValue,
)
from app.news.schemas import SetupCatalystContextLabel


@dataclass(frozen=True)
class ForecastDecision:
    forecast_value: Optional[str]
    evidence_quality: EvidenceQualityState
    evidence_refs: list[str] = field(default_factory=list)
    rationale: str = ""
    zone_ref: Optional[str] = None
    abstention_reason: Optional[AbstentionReason] = None

    @property
    def abstained(self) -> bool:
        return self.forecast_value is None


def _abstain(quality: EvidenceQualityState, reason: AbstentionReason, rationale: str) -> ForecastDecision:
    return ForecastDecision(
        forecast_value=None, evidence_quality=quality, rationale=rationale, abstention_reason=reason
    )


def _insufficiency_reason(packet: EvidencePacket) -> AbstentionReason:
    """(#C) Picks the most specific applicable abstention reason from the
    packet's own research diagnostics, in a fixed priority order -- never a
    generic catch-all when a more specific reason is available."""
    research = packet.historical_research
    if research is None:
        return AbstentionReason.INSUFFICIENT_HISTORICAL_ANALOGS
    composition = research.independence.sample_composition
    if not composition.purged_counts_by_horizon or all(
        c < 20 for c in composition.purged_counts_by_horizon.values()
    ):
        return AbstentionReason.TOO_FEW_PURGED_EPISODES
    if research.overlap.overlap_fraction >= 0.75:
        return AbstentionReason.HIGH_OVERLAP
    if any(c.status.value == "assumption_not_supported_in_this_sample" for c in research.contradictions):
        return AbstentionReason.CONTRADICTORY_RESEARCH
    if research.independence.walk_forward.stability.value == "unstable":
        return AbstentionReason.UNSTABLE_EVIDENCE
    return AbstentionReason.UNSTABLE_EVIDENCE


def generate_direction_forecast(packet: EvidencePacket, config: ForecastConfig) -> ForecastDecision:
    quality = classify_evidence_quality(packet, config)
    if packet.setup is None:
        return _abstain(
            quality,
            AbstentionReason.INSUFFICIENT_HISTORICAL_ANALOGS,
            "No targeted setup on this packet -- a deterministic direction call requires a "
            "qualified/rejected setup's own directional thesis to ground the forecast in.",
        )
    if quality in (EvidenceQualityState.INSUFFICIENT_EVIDENCE, EvidenceQualityState.WEAK_EVIDENCE):
        return _abstain(
            quality,
            _insufficiency_reason(packet),
            "Evidence quality is too weak to support a directional forecast.",
        )

    value = (
        DirectionForecastValue.UP.value
        if packet.setup.candidate.direction.value == "bullish"
        else DirectionForecastValue.DOWN.value
    )
    return ForecastDecision(
        forecast_value=value,
        evidence_quality=quality,
        evidence_refs=[f"setup:{packet.setup.candidate.id}"],
        rationale=f"Directional call follows the {packet.setup.candidate.setup_type.value} "
        f"setup's own already-qualified direction.",
    )


def generate_structure_forecast(packet: EvidencePacket, config: ForecastConfig) -> ForecastDecision:
    quality = classify_evidence_quality(packet, config)
    if packet.setup is None:
        return _abstain(
            quality,
            AbstentionReason.INSUFFICIENT_HISTORICAL_ANALOGS,
            "No targeted setup on this packet to bind a structure forecast to.",
        )
    if quality in (EvidenceQualityState.INSUFFICIENT_EVIDENCE, EvidenceQualityState.WEAK_EVIDENCE):
        return _abstain(
            quality,
            _insufficiency_reason(packet),
            "Evidence quality is too weak to support a structure forecast.",
        )
    bullish = packet.setup.candidate.direction.value == "bullish"
    sr = packet.support_resistance
    zone = sr.nearest_resistance if bullish else sr.nearest_support
    if zone is None:
        return _abstain(
            quality,
            AbstentionReason.INSUFFICIENT_HISTORICAL_ANALOGS,
            "No nearest support/resistance zone available on the setup's own side to forecast against.",
        )
    value = (
        StructureForecastValue.RESISTANCE_BREAKS.value
        if bullish
        else StructureForecastValue.SUPPORT_FAILS.value
    )
    return ForecastDecision(
        forecast_value=value,
        evidence_quality=quality,
        evidence_refs=[f"setup:{packet.setup.candidate.id}", f"zone:{zone.id}"],
        zone_ref=zone.id,
        rationale=f"The {packet.setup.candidate.setup_type.value} setup's direction implies the "
        f"nearest {'resistance' if bullish else 'support'} zone eventually gives way.",
    )


def generate_volatility_forecast(packet: EvidencePacket, config: ForecastConfig) -> ForecastDecision:
    atr = packet.features.atr
    rvol_feature = packet.features.intraday_relative_volume
    rvol_missing = rvol_feature is None or rvol_feature.intraday_relative_volume is None
    if atr is None or atr.value is None or rvol_missing:
        return _abstain(
            EvidenceQualityState.INSUFFICIENT_EVIDENCE,
            AbstentionReason.STALE_DATA,
            "ATR or intraday relative volume unavailable -- cannot ground a volatility forecast.",
        )
    rvol = rvol_feature.intraday_relative_volume
    quality = (
        EvidenceQualityState.MIXED_EVIDENCE if 0.8 <= rvol <= 1.5 else EvidenceQualityState.WEAK_EVIDENCE
    )
    value = (
        VolatilityForecastValue.EXPANDS.value if rvol >= 1.5 else VolatilityForecastValue.CONTRACTS.value
    )
    return ForecastDecision(
        forecast_value=value,
        evidence_quality=quality,
        evidence_refs=["structure:breaks_of_structure"],
        rationale=f"Current relative volume ({rvol:.2f}x) is the basis for the volatility call.",
    )


def generate_catalyst_reaction_forecast(packet: EvidencePacket, config: ForecastConfig) -> ForecastDecision:
    catalyst = packet.catalyst_context
    if catalyst is None or catalyst.nearest_catalyst is None:
        return _abstain(
            EvidenceQualityState.INSUFFICIENT_EVIDENCE,
            AbstentionReason.CATALYST_AMBIGUITY,
            "No catalyst context available to forecast reaction persistence.",
        )
    if catalyst.label in (
        SetupCatalystContextLabel.CATALYST_TIMING_AMBIGUOUS,
        SetupCatalystContextLabel.NO_RECENT_CATALYST,
    ):
        return _abstain(
            EvidenceQualityState.INSUFFICIENT_EVIDENCE,
            AbstentionReason.CATALYST_AMBIGUITY,
            f"Catalyst context is {catalyst.label.value}, too ambiguous to forecast reaction persistence.",
        )
    if catalyst.label in (
        SetupCatalystContextLabel.CATALYST_REACTION_FADED,
        SetupCatalystContextLabel.CATALYST_REACTION_PERSISTED,
    ):
        return _abstain(
            EvidenceQualityState.INSUFFICIENT_EVIDENCE,
            AbstentionReason.CATALYST_AMBIGUITY,
            f"Catalyst reaction already resolved to {catalyst.label.value} as of this packet -- "
            "nothing further to forecast at this horizon.",
        )

    value = (
        CatalystReactionForecastValue.PERSISTS.value
        if catalyst.label == SetupCatalystContextLabel.CATALYST_SUPPORTED
        else CatalystReactionForecastValue.FADES.value
    )
    return ForecastDecision(
        forecast_value=value,
        evidence_quality=EvidenceQualityState.MIXED_EVIDENCE,
        evidence_refs=[f"catalyst:{catalyst.nearest_catalyst.event_id}"],
        rationale=catalyst.label_basis,
    )


def generate_setup_outcome_forecast(packet: EvidencePacket, config: ForecastConfig) -> ForecastDecision:
    quality = classify_evidence_quality(packet, config)
    if packet.setup is None:
        return _abstain(
            quality,
            AbstentionReason.INSUFFICIENT_HISTORICAL_ANALOGS,
            "No targeted setup on this packet to forecast an outcome for.",
        )
    if not packet.setup.qualified:
        return _abstain(
            quality,
            AbstentionReason.RANKING_GATE_RESTRICTION,
            "Setup is not qualified -- a setup-outcome forecast is only made for qualified setups.",
        )
    if quality in (EvidenceQualityState.INSUFFICIENT_EVIDENCE, EvidenceQualityState.WEAK_EVIDENCE):
        return _abstain(
            quality,
            _insufficiency_reason(packet),
            "Evidence quality is too weak to support a setup-outcome forecast.",
        )

    return ForecastDecision(
        forecast_value=SetupOutcomeForecastValue.FAVORABLE_BEFORE_ADVERSE.value,
        evidence_quality=quality,
        evidence_refs=[f"setup:{packet.setup.candidate.id}"],
        rationale="Qualified setup with supporting historical research; forecasting favorable "
        "excursion is reached before adverse excursion.",
    )


_GENERATORS = {
    ForecastCategory.DIRECTION: generate_direction_forecast,
    ForecastCategory.STRUCTURE: generate_structure_forecast,
    ForecastCategory.VOLATILITY: generate_volatility_forecast,
    ForecastCategory.CATALYST_REACTION: generate_catalyst_reaction_forecast,
    ForecastCategory.SETUP_OUTCOME: generate_setup_outcome_forecast,
}


def generate_deterministic_forecast(
    packet: EvidencePacket,
    category: ForecastCategory,
    config: ForecastConfig = DEFAULT_FORECAST_CONFIG,
) -> ForecastDecision:
    return _GENERATORS[category](packet, config)
