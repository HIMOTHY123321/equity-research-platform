"""Typed News/Catalyst Context outputs (Phase 10).

Nothing here is a trading signal: `MarketReaction` is a descriptive
measurement (reusing `app.research.outcomes`' own horizon/excursion math,
never a duplicate implementation), and `SetupCatalystContext.label` is one of
a small, explicitly-defined, deterministic set of descriptive states -- never
a buy/sell recommendation or a 0-100 score (see ADR 0013 and Phase 9's
RANKING GATE decision, which this phase does not revisit).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.research.schemas import EvaluationQuality, ExcursionMetrics, HorizonOutcome


class CatalystCategory(str, Enum):
    """Deterministic normalized catalyst taxonomy (Phase 10 section C).
    `UNKNOWN` is a real, valid, permanent category -- never a placeholder
    that classification is expected to eliminate; an article with no
    matching rule stays honestly UNKNOWN rather than being force-fit."""

    EARNINGS = "earnings"
    EARNINGS_PREANNOUNCEMENT = "earnings_preannouncement"
    GUIDANCE = "guidance"
    ANALYST_RATING = "analyst_rating"
    PRICE_TARGET = "price_target"
    PRODUCT_LAUNCH = "product_launch"
    PRODUCT_ISSUE = "product_issue"
    REGULATORY = "regulatory"
    LEGAL_LAWSUIT = "legal_lawsuit"
    MERGER_ACQUISITION = "merger_acquisition"
    FINANCING_CAPITAL_RAISE = "financing_capital_raise"
    BUYBACK = "buyback"
    DIVIDEND = "dividend"
    MANAGEMENT_CHANGE = "management_change"
    FILING = "filing"
    MACROECONOMIC = "macroeconomic"
    FEDERAL_RESERVE = "federal_reserve"
    INTEREST_RATES = "interest_rates"
    INFLATION = "inflation"
    EMPLOYMENT = "employment"
    GEOPOLITICAL = "geopolitical"
    SUPPLY_CHAIN = "supply_chain"
    SECTOR_INDUSTRY = "sector_industry"
    COMPANY_SPECIFIC_OTHER = "company_specific_other"
    UNKNOWN = "unknown"


class ClassificationMethod(str, Enum):
    """(Section C) Every article's classification records how it was
    produced. Phase 10 only ever writes DETERMINISTIC_RULE -- AI_ASSISTED
    exists so a future layer has somewhere to record itself without ever
    silently overwriting the deterministic result (see ADR 0013): an
    AI-assisted classification, if ever added, must be a *separate*
    `CatalystClassification` attached alongside this one, never a mutation
    of it."""

    DETERMINISTIC_RULE = "deterministic_rule"
    AI_ASSISTED = "ai_assisted"


class ClassificationBasis(str, Enum):
    """(Section C, M) Discrete, inspectable tiers -- deliberately not a
    fabricated confidence float. Each tier is a specific, testable condition
    in app.news.classification, never a judgment call."""

    PROVIDER_CATEGORY_DIRECT_MAP = "provider_category_direct_map"
    STRONG_KEYWORD_MATCH = "strong_keyword_match"
    WEAK_KEYWORD_FALLBACK = "weak_keyword_fallback"
    UNKNOWN_NO_MATCH = "unknown_no_match"


class CatalystClassification(BaseModel):
    """(Section C) The full evidence behind one article's `category` --
    never just the label on its own. `provider_raw_category` is preserved
    verbatim even when it disagrees with or is unused by the deterministic
    mapping, so raw provider metadata is never silently discarded."""

    model_config = ConfigDict(frozen=True)

    category: CatalystCategory
    basis: ClassificationBasis
    matched_rules: list[str] = []
    provider_raw_category: Optional[str] = None
    method: ClassificationMethod = ClassificationMethod.DETERMINISTIC_RULE


class NormalizedNewsArticle(BaseModel):
    """(Section B) The one normalized article representation every provider
    maps into -- no provider-specific dict shape ever leaks past
    `app.news.normalization`. Deliberately does NOT store full article
    bodies (never licensed for redistribution here); `headline` plus
    structured metadata plus `url` (linking to the original source) is the
    complete content surface. Frozen/immutable: a later re-ingestion of the
    same source article produces the same `article_id` and is deduplicated
    by the repository, never mutated in place (see app.news.repository)."""

    model_config = ConfigDict(frozen=True)

    article_id: str
    provider: str
    source: Optional[str] = None
    headline: str
    published_at: datetime
    received_at: Optional[datetime] = None
    url: Optional[str] = None
    symbols: tuple[str, ...] = ()
    raw_category: Optional[str] = None
    classification: CatalystClassification
    provenance: dict = {}
    ingested_at: datetime


class CatalystEvent(BaseModel):
    """(Section D) A deterministic grouping of one or more
    `NormalizedNewsArticle`s that report the same underlying catalyst.
    Every source article is preserved (`contributing_article_ids`) -- this
    is a grouping layer on top of the raw articles, never a replacement for
    them, same "raw data is never deleted or merged away" convention
    `SetupEpisode` already uses for setups (ADR 0012)."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    primary_timestamp: datetime
    category: CatalystCategory
    affected_symbols: tuple[str, ...]
    contributing_article_ids: list[str]
    source_count: int
    earliest_published_at: datetime
    latest_update_at: datetime
    title: str
    provenance: dict = {}


class ReactionSession(str, Enum):
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    WEEKEND_NON_TRADING = "weekend_non_trading"


class MarketReaction(BaseModel):
    """(Section F) What actually happened after a catalyst, for one
    symbol/timeframe. Price/volume horizons reuse
    `app.research.outcomes.compute_horizon_outcomes`/`compute_excursion`
    verbatim (same `HorizonOutcome`/`ExcursionMetrics` shapes Phase 7
    already built and tested) rather than a parallel implementation.
    Structure fields are attached by the linking layer (app.news.reaction)
    from already-computed Phase 4/5 snapshots at the event's own timestamp
    -- never recomputed here."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    symbol: str
    timeframe: str
    session_at_event: ReactionSession
    base_price: Optional[float] = None
    price_horizons: list[HorizonOutcome] = []
    mfe: Optional[ExcursionMetrics] = None
    mae: Optional[ExcursionMetrics] = None
    rvol_at_event: Optional[float] = None
    volume_spike_ratio: Optional[float] = None
    atr_normalized_move: Optional[float] = None
    nearest_support_price: Optional[float] = None
    nearest_resistance_price: Optional[float] = None
    structure_state_at_event: Optional[str] = None
    bos_after_event: bool = False
    choch_after_event: bool = False
    gap_created: Optional[bool] = None
    evaluation_quality: Optional[EvaluationQuality] = None
    computed_at: datetime


class SetupCatalystContextLabel(str, Enum):
    """(Section G) A small, fixed, descriptive vocabulary -- deliberately
    NOT bullish/bearish/buy/sell. Each label has one explicit, deterministic
    definition in app.news.setup_linking; never a subjective call."""

    CATALYST_SUPPORTED = "catalyst_supported_context"
    CATALYST_CONFLICTED = "catalyst_conflicted_context"
    CATALYST_REACTION_FADED = "catalyst_reaction_faded"
    CATALYST_REACTION_PERSISTED = "catalyst_reaction_persisted"
    CATALYST_TIMING_AMBIGUOUS = "catalyst_timing_ambiguous"
    NO_RECENT_CATALYST = "no_recent_catalyst_found"


class CatalystReference(BaseModel):
    """One catalyst event as seen from a setup's perspective -- just enough
    to identify and time-locate it; the full `CatalystEvent`/`MarketReaction`
    are fetched separately by `event_id` (VIEW CATALYST)."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    category: CatalystCategory
    primary_timestamp: datetime
    source_count: int
    hours_before_setup: Optional[float] = None
    hours_after_setup: Optional[float] = None


class SetupCatalystContext(BaseModel):
    """(Section G) The complete catalyst picture for one setup candidate,
    computed strictly from catalysts known as of the setup's own
    `candidate_candle_timestamp` -- see app.news.setup_linking for the exact
    as_of discipline. Descriptive only: no score, no recommendation."""

    model_config = ConfigDict(frozen=True)

    setup_id: str
    symbol: str
    catalysts_before: list[CatalystReference] = []
    catalysts_after: list[CatalystReference] = []
    nearest_catalyst: Optional[CatalystReference] = None
    nearest_reaction: Optional[MarketReaction] = None
    label: SetupCatalystContextLabel
    label_basis: str
