"""Typed market-structure outputs. The pivot_timestamp/confirmed_at split on
SwingPoint is the single most important pair of fields in this package — see
docs/decisions for the full lookahead-safety rationale.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.market_structure.common import StructureStatus
from app.schemas.market_data import Timeframe


class SwingType(str, Enum):
    HIGH = "high"
    LOW = "low"


class SwingClassification(str, Enum):
    HIGHER_HIGH = "higher_high"
    LOWER_HIGH = "lower_high"
    EQUAL_HIGH = "equal_high"
    HIGHER_LOW = "higher_low"
    LOWER_LOW = "lower_low"
    EQUAL_LOW = "equal_low"


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class TrendClass(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGING = "ranging"
    INSUFFICIENT_DATA = "insufficient_data"


class TrendStrength(str, Enum):
    WEAK = "weak"
    DEVELOPING = "developing"
    ESTABLISHED = "established"


class SwingPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: SwingType
    price: float
    pivot_timestamp: datetime
    confirmed_at: datetime
    left_bars: int
    right_bars: int

    classification: Optional[SwingClassification] = None
    previous_comparable_price: Optional[float] = None

    is_broken: bool = False
    first_broken_at: Optional[datetime] = None
    break_direction: Optional[Direction] = None


class CandidatePivot(BaseModel):
    """A bar that looks like a local extreme using only the right-side bars
    available so far — NOT yet evaluable against the full `right_bars` rule.
    Never treated as structure; exposed purely for visibility."""

    model_config = ConfigDict(frozen=True)

    type: SwingType
    price: float
    pivot_timestamp: datetime
    left_bars: int
    right_bars_required: int
    right_bars_available: int


class TrendClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    trend: TrendClass
    strength: Optional[TrendStrength] = None
    evidence: list[str] = []


class BreakOfStructureEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    direction: Direction
    broken_level: float
    broken_swing_timestamp: datetime
    break_timestamp: datetime
    confirmation: str = "close"
    distance_beyond_level: float


class ChangeOfCharacterEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    direction: Direction
    prior_structure: Direction
    broken_level: float
    break_timestamp: datetime
    reference_swing_timestamp: datetime


class ActiveRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: StructureStatus
    high: Optional[float] = None
    low: Optional[float] = None
    midpoint: Optional[float] = None
    width: Optional[float] = None
    width_percent: Optional[float] = None
    position_percent: Optional[float] = None


class Freshness(BaseModel):
    model_config = ConfigDict(frozen=True)

    bars_since_last_swing_high: Optional[int] = None
    bars_since_last_swing_low: Optional[int] = None
    bars_since_last_bullish_bos: Optional[int] = None
    bars_since_last_bearish_bos: Optional[int] = None
    bars_since_last_choch: Optional[int] = None


class StructureDataQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_timeframe: Timeframe
    candle_count: int
    completed_candle_count: int
    earliest_candle_timestamp: Optional[datetime] = None
    latest_candle_timestamp: Optional[datetime] = None
    confirmed_swing_count: int = 0
    candidate_swing_count: int = 0
    future_candles_dropped: int = 0
    warnings: list[str] = []


class MarketStructureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    as_of: datetime

    trend: TrendClassification

    swings: list[SwingPoint]
    candidate_swings: list[CandidatePivot]

    latest_swing_high: Optional[SwingPoint] = None
    latest_swing_low: Optional[SwingPoint] = None
    latest_higher_high: Optional[SwingPoint] = None
    latest_higher_low: Optional[SwingPoint] = None
    latest_lower_high: Optional[SwingPoint] = None
    latest_lower_low: Optional[SwingPoint] = None

    breaks_of_structure: list[BreakOfStructureEvent]
    changes_of_character: list[ChangeOfCharacterEvent]

    active_range: ActiveRange
    freshness: Freshness
    data_quality: StructureDataQuality


class TimeframeStructureSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: Timeframe
    trend: TrendClass
    strength: Optional[TrendStrength] = None


class MultiTimeframeStructureSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: datetime
    by_timeframe: dict[str, TimeframeStructureSummary]
    higher_timeframe_alignment: Optional[str] = None
