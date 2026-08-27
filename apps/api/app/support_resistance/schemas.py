"""Typed support/resistance outputs. Every zone traces back to the raw
levels underneath it — see docs/decisions for the full explainability
design (RawLevel -> Zone -> ZoneExplanation).
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.market_data import Timeframe


class LevelKind(str, Enum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    REFERENCE = "reference"


class InteractionType(str, Enum):
    TOUCH = "touch"
    REJECTION = "rejection"
    WICK_BREACH = "wick_breach"
    CLOSE_BREAK = "close_break"


class ZoneLifecycle(str, Enum):
    ACTIVE = "active"
    TESTED = "tested"
    WEAKENED = "weakened"
    BROKEN = "broken"
    STALE = "stale"


class Position(str, Enum):
    ABOVE_PRICE = "above_price"
    BELOW_PRICE = "below_price"
    CONTAINS_PRICE = "contains_price"


class RawLevel(BaseModel):
    """A single piece of evidence. Never mutated or deleted once produced —
    zones are a non-destructive view over a collection of these."""

    model_config = ConfigDict(frozen=True)

    id: str
    price: float
    kind: LevelKind
    source: str
    source_timeframe: Timeframe
    origin_timestamp: datetime
    known_at: datetime
    metadata: dict = {}


class ZoneEvidenceEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    source_timeframe: Timeframe
    price: float
    origin_timestamp: datetime
    known_at: datetime
    weight: float


class ZoneInteraction(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    interaction_type: InteractionType
    high: float
    low: float
    close: float
    distance: float
    is_independent: bool


class BreakEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    direction: LevelKind  # SUPPORT (broke down) or RESISTANCE (broke up)
    break_price: float
    first_broken_at: datetime
    zone_lower_bound: float
    zone_upper_bound: float


class StrengthBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_score: float
    confluence_score: float
    interaction_score: float
    recency_score: float
    total: float


class ConfluenceInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_count: int
    timeframe_count: int
    source_types: list[str]
    timeframes: list[Timeframe]


class InteractionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    independent_touches: int
    rejections: int
    wick_breaches: int


class PriceRelationship(BaseModel):
    model_config = ConfigDict(frozen=True)

    distance_absolute: float
    distance_percent: float
    position: Position


class ZoneFreshness(BaseModel):
    model_config = ConfigDict(frozen=True)

    bars_since_created: Optional[int] = None
    bars_since_last_touch: Optional[int] = None
    bars_since_last_rejection: Optional[int] = None
    bars_since_break: Optional[int] = None


class Zone(BaseModel):
    """A non-destructive cluster of RawLevels. `member_levels` always
    preserves the full original evidence -- nothing about a zone's
    provenance is ever thrown away."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: LevelKind
    lower_bound: float
    upper_bound: float
    representative_price: float

    member_levels: list[RawLevel]
    evidence: list[ZoneEvidenceEntry]
    confluence: ConfluenceInfo

    known_at: datetime
    interactions: list[ZoneInteraction]
    interaction_summary: InteractionSummary
    break_event: Optional[BreakEvent] = None

    lifecycle: ZoneLifecycle
    strength: StrengthBreakdown
    freshness: ZoneFreshness
    price_relationship: Optional[PriceRelationship] = None


class ZoneExplanation(BaseModel):
    """Dedicated explainability payload -- this is what powers a future
    "why is this resistance?" UI. Purely a re-presentation of data already
    on the Zone; never independently computed."""

    model_config = ConfigDict(frozen=True)

    zone_id: str
    reason: str
    evidence: list[ZoneEvidenceEntry]
    interaction_summary: InteractionSummary
    strength_breakdown: StrengthBreakdown


class SupportResistanceDataQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_timeframe: Timeframe
    candles_consumed: int
    raw_levels_generated: int
    zones_created: int
    confirmed_swings_used: int
    warnings: list[str] = []


class SupportResistanceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    as_of: datetime

    nearest_support: Optional[Zone] = None
    nearest_resistance: Optional[Zone] = None

    active_support_zones: list[Zone]
    active_resistance_zones: list[Zone]
    reference_levels: list[RawLevel]

    recent_broken_zones: list[Zone]

    data_quality: SupportResistanceDataQuality
