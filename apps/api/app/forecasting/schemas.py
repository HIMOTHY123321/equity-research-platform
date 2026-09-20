"""Phase 12: Forward Prediction Benchmark & Validation Lab.

A ForwardForecast is a bounded, machine-evaluable hypothesis locked at
`market_as_of`, bound to a frozen EvidencePacket, resolved strictly later by
`app.forecasting.resolver` -- the one and only place future data may enter
this package (mirroring `app.research.outcomes`' own "one place allowed to
look at candles after detection" discipline, ADR 0008).

Every forecast is either a real, machine-evaluable prediction from a closed
enum of states (never a price target, never a probability, never free
prose) or an explicit abstention with a recorded reason. Both are the same
record type (`status` distinguishes them) so abstention rate is always
computed from the same ledger the forecasts themselves live in, never a
separate, easy-to-forget table.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

FORECAST_SCHEMA_VERSION = "1.0"


class ForecastCategory(str, Enum):
    DIRECTION = "direction"
    STRUCTURE = "structure"
    VOLATILITY = "volatility"
    CATALYST_REACTION = "catalyst_reaction"
    SETUP_OUTCOME = "setup_outcome"


class DirectionForecastValue(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat_indeterminate"


class StructureForecastValue(str, Enum):
    SUPPORT_HOLDS = "support_holds"
    SUPPORT_FAILS = "support_fails"
    RESISTANCE_BREAKS = "resistance_breaks"
    RESISTANCE_REJECTS = "resistance_rejects"
    BOS_OCCURS = "bos_occurs"
    CHOCH_OCCURS = "choch_occurs"
    RANGE_PERSISTS = "range_persists"
    RANGE_RESOLVES = "range_resolves"


class VolatilityForecastValue(str, Enum):
    EXPANDS = "volatility_expands"
    CONTRACTS = "volatility_contracts"


class CatalystReactionForecastValue(str, Enum):
    PERSISTS = "reaction_persists"
    FADES = "reaction_fades"


class SetupOutcomeForecastValue(str, Enum):
    FAVORABLE_BEFORE_ADVERSE = "favorable_before_adverse"
    INVALIDATES_BEFORE_CONFIRMATION = "invalidates_before_confirmation"
    REMAINS_UNRESOLVED = "remains_unresolved"


# The one and only place a forecast_value string is accepted as legitimate
# for a given category -- both the deterministic engine and the AI-synthesis
# path are validated against this closed set; nothing else is ever allowed
# to reach a persisted ForwardForecast (#D "AI may not invent new outcome
# types").
FORECAST_VALUES_BY_CATEGORY: dict[ForecastCategory, frozenset[str]] = {
    ForecastCategory.DIRECTION: frozenset(v.value for v in DirectionForecastValue),
    ForecastCategory.STRUCTURE: frozenset(v.value for v in StructureForecastValue),
    ForecastCategory.VOLATILITY: frozenset(v.value for v in VolatilityForecastValue),
    ForecastCategory.CATALYST_REACTION: frozenset(v.value for v in CatalystReactionForecastValue),
    ForecastCategory.SETUP_OUTCOME: frozenset(v.value for v in SetupOutcomeForecastValue),
}


class EvidenceQualityState(str, Enum):
    """(#E) Categorical, derived only from already-computed Phase 8/9
    research-quality fields (evidence maturity, conclusion stability,
    overlap, concentration) -- never a model confidence score, never a
    probability. See app.forecasting.evidence_quality for the deterministic
    derivation."""

    HIGH_EVIDENCE_SUPPORT = "high_evidence_support"
    MIXED_EVIDENCE = "mixed_evidence"
    WEAK_EVIDENCE = "weak_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AbstentionReason(str, Enum):
    TOO_FEW_PURGED_EPISODES = "too_few_purged_episodes"
    HIGH_OVERLAP = "high_overlap"
    UNSTABLE_EVIDENCE = "unstable_evidence"
    CONTRADICTORY_RESEARCH = "contradictory_research"
    INSUFFICIENT_HISTORICAL_ANALOGS = "insufficient_historical_analogs"
    STALE_DATA = "stale_data"
    PROVIDER_LIMITATION = "provider_limitation"
    CATALYST_AMBIGUITY = "catalyst_ambiguity"
    RANKING_GATE_RESTRICTION = "ranking_gate_restriction"


class ForecastOrigin(str, Enum):
    DETERMINISTIC_RESEARCH = "deterministic_research"
    AI_SYNTHESIS = "ai_synthesis"


class ForecastStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ABSTAINED = "abstained"
    INVALIDATED = "invalidated"


class ForecastRunMode(str, Enum):
    """(#J) A forecast created through the real, product-facing endpoint is
    always PROSPECTIVE -- `market_as_of` is required to be within a small
    tolerance of real "now" at creation time (enforced by the API route,
    not by this schema), which is what makes backfilling structurally
    impossible rather than merely discouraged. BACKTEST_REPLAY exists only
    for internal resolver testing against historical fixtures and is never
    reachable from the public API -- see ADR 0016 for why a full
    product-facing backtest-forecast feature was deliberately not built."""

    PROSPECTIVE = "prospective"
    BACKTEST_REPLAY = "backtest_replay"


class ForecastOutcomeCategory(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    NEUTRAL_UNRESOLVED = "neutral_unresolved"
    INVALIDATED = "invalidated"
    INSUFFICIENT_FUTURE_DATA = "insufficient_future_data"


class ForwardForecast(BaseModel):
    """(#A/#F) Immutable once created. `forecast_id` is a deterministic
    sha256 of its own identity fields (symbol/timeframe/market_as_of/
    forecast_category/evidence_packet_id), matching the article_id/event_id/
    packet_id convention elsewhere -- a duplicate creation attempt for the
    exact same instant is idempotent, never a silent second row."""

    model_config = ConfigDict(frozen=True)

    forecast_id: str
    schema_version: str = FORECAST_SCHEMA_VERSION
    created_at: datetime
    market_as_of: datetime
    symbol: str
    timeframe: str

    forecast_category: ForecastCategory
    forecast_value: Optional[str] = None
    forecast_horizon_bars: int
    zone_ref: Optional[str] = None

    # Denormalized breakdown keys (#H/#K "by setup"/"by catalyst") -- copied
    # from the EvidencePacket at creation time purely so performance
    # breakdowns never have to re-fetch/re-derive them; never used for
    # anything else, and never diverge from the packet since both are
    # frozen at the same instant.
    setup_type: Optional[str] = None
    catalyst_category: Optional[str] = None

    evidence_packet_id: str
    evidence_packet_schema_version: str
    pipeline_version: str
    evidence_refs: list[str] = []
    evidence_quality: EvidenceQualityState

    origin: ForecastOrigin
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None

    status: ForecastStatus
    abstention_reason: Optional[AbstentionReason] = None
    rationale: str = ""
    run_mode: ForecastRunMode = ForecastRunMode.PROSPECTIVE

    @model_validator(mode="after")
    def _validate_closed_set(self) -> "ForwardForecast":
        if self.status == ForecastStatus.ABSTAINED:
            if self.forecast_value is not None:
                raise ValueError("an abstained forecast must not carry a forecast_value")
            if self.abstention_reason is None:
                raise ValueError("an abstained forecast must record an abstention_reason")
            return self

        if self.forecast_value is None:
            raise ValueError("a non-abstained forecast must carry a forecast_value")
        allowed = FORECAST_VALUES_BY_CATEGORY[self.forecast_category]
        if self.forecast_value not in allowed:
            raise ValueError(
                f"{self.forecast_value!r} is not a valid value for {self.forecast_category.value}; "
                f"allowed: {sorted(allowed)}"
            )
        return self


class ForecastOutcome(BaseModel):
    """(#G) Produced strictly after the horizon closes, by
    app.forecasting.resolver alone. Never mutates or replaces the
    ForwardForecast it resolves -- `forecast_id` links them, both rows
    persist forever."""

    model_config = ConfigDict(frozen=True)

    outcome_id: str
    forecast_id: str
    resolved_at: datetime
    resolution_as_of: datetime
    outcome: ForecastOutcomeCategory
    # The resolved state in the same closed vocabulary as `forecast_value`
    # (e.g. "up"/"down"/"flat_indeterminate" for DIRECTION) where the
    # category has one -- what baselines/metrics group and compare against,
    # kept separate from the forecast-relative `outcome` (correct/incorrect)
    # above so "what actually happened" is never conflated with "was the
    # forecast right."
    actual_value: Optional[str] = None
    actual_forward_return_percent: Optional[float] = None
    actual_mfe_atr: Optional[float] = None
    actual_mae_atr: Optional[float] = None
    market_data_cutoff: Optional[datetime] = None
    detail: str = ""
