"""The single entry point: (candles, structure snapshots) -> SupportResistanceSnapshot.

Same as-of/no-lookahead discipline as Phases 3-4: every candle series is
defensively re-truncated to `as_of`, and a zone's own eligible-candle window
starts at `zone.known_at` (the moment its last-confirmed member became
knowable) -- never earlier, so a zone can never appear to have been
"touched" before it structurally existed. See the ADR for the full
worked walkthrough.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.market_structure.common import completed_only, truncate_to_as_of
from app.market_structure.schemas import MarketStructureSnapshot
from app.schemas.market_data import Candle, Timeframe
from app.support_resistance.breaks import detect_zone_break
from app.support_resistance.clustering import ClusteredZone, cluster_levels
from app.support_resistance.config import DEFAULT_SUPPORT_RESISTANCE_CONFIG, SupportResistanceConfig
from app.support_resistance.interactions import detect_interactions
from app.support_resistance.lifecycle import compute_freshness, determine_lifecycle
from app.support_resistance.multi_timeframe import extract_swing_levels
from app.support_resistance.nearest import (
    compute_price_relationship,
    nearest_resistance_above,
    nearest_support_below,
)
from app.support_resistance.schemas import (
    InteractionSummary,
    InteractionType,
    LevelKind,
    RawLevel,
    SupportResistanceDataQuality,
    SupportResistanceSnapshot,
    Zone,
    ZoneLifecycle,
)
from app.support_resistance.sources import (
    extract_previous_day_levels,
    extract_previous_week_levels,
    extract_session_open_level,
)
from app.support_resistance.strength import compute_strength

# Relevance ranking (#26): balances strength against how far away a zone is,
# so a very strong zone 40% away doesn't crowd out a moderate zone that's
# actually relevant to current price.
RELEVANCE_DISTANCE_PENALTY_PER_PERCENT = 2.0
RELEVANCE_MAX_DISTANCE_PENALTY = 40.0


def compute_support_resistance_snapshot(
    symbol: str,
    timeframe: Timeframe,
    primary_candles: list[Candle],
    daily_candles: list[Candle],
    structure_snapshots: dict[Timeframe, MarketStructureSnapshot],
    as_of: datetime,
    config: SupportResistanceConfig = DEFAULT_SUPPORT_RESISTANCE_CONFIG,
) -> SupportResistanceSnapshot:
    primary_truncated, _ = truncate_to_as_of(primary_candles, as_of)
    primary_completed = completed_only(primary_truncated, as_of)
    daily_truncated, _ = truncate_to_as_of(daily_candles, as_of)

    warnings: list[str] = []

    raw_levels: list[RawLevel] = []
    raw_levels += extract_previous_day_levels(daily_truncated, as_of)
    raw_levels += extract_previous_week_levels(daily_truncated, as_of)
    raw_levels += extract_session_open_level(daily_truncated, as_of)
    swing_levels = extract_swing_levels(structure_snapshots, as_of)
    raw_levels += swing_levels

    reference_levels = [lvl for lvl in raw_levels if lvl.kind == LevelKind.REFERENCE]
    clusterable_levels = [lvl for lvl in raw_levels if lvl.kind != LevelKind.REFERENCE]

    resistance_clusters = cluster_levels(clusterable_levels, LevelKind.RESISTANCE, config)
    support_clusters = cluster_levels(clusterable_levels, LevelKind.SUPPORT, config)

    current_price = primary_truncated[-1].close if primary_truncated else None

    all_zones = [
        _build_zone(cluster, primary_completed, current_price, config)
        for cluster in resistance_clusters + support_clusters
    ]

    active_zones = [z for z in all_zones if z.lifecycle != ZoneLifecycle.BROKEN]
    broken_zones = [z for z in all_zones if z.lifecycle == ZoneLifecycle.BROKEN]

    active_support = [z for z in active_zones if z.kind == LevelKind.SUPPORT]
    active_resistance = [z for z in active_zones if z.kind == LevelKind.RESISTANCE]

    nearest_support = (
        nearest_support_below(active_zones, current_price) if current_price is not None else None
    )
    nearest_resistance = (
        nearest_resistance_above(active_zones, current_price) if current_price is not None else None
    )

    ranked_support = _rank_by_relevance(active_support)[: config.max_zones_in_snapshot]
    ranked_resistance = _rank_by_relevance(active_resistance)[: config.max_zones_in_snapshot]
    ranked_broken = sorted(
        broken_zones,
        key=lambda z: z.break_event.first_broken_at if z.break_event else z.known_at,
        reverse=True,
    )[: config.max_recent_broken_zones_in_snapshot]
    ranked_reference = sorted(reference_levels, key=lambda lvl: lvl.known_at, reverse=True)[
        : config.max_reference_levels_in_snapshot
    ]

    if not primary_completed:
        warnings.append("No completed candles available for interaction/break detection")
    if not raw_levels:
        warnings.append("No raw levels available from any source")

    data_quality = SupportResistanceDataQuality(
        source_timeframe=timeframe,
        candles_consumed=len(primary_completed),
        raw_levels_generated=len(raw_levels),
        zones_created=len(all_zones),
        confirmed_swings_used=len(swing_levels),
        warnings=warnings,
    )

    return SupportResistanceSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        as_of=as_of,
        nearest_support=nearest_support,
        nearest_resistance=nearest_resistance,
        active_support_zones=ranked_support,
        active_resistance_zones=ranked_resistance,
        reference_levels=ranked_reference,
        recent_broken_zones=ranked_broken,
        data_quality=data_quality,
    )


def _build_zone(
    cluster: ClusteredZone,
    primary_completed: list[Candle],
    current_price: Optional[float],
    config: SupportResistanceConfig,
) -> Zone:
    zone_candles = [c for c in primary_completed if c.timestamp >= cluster.known_at]

    break_event = detect_zone_break(
        zone_candles, cluster.kind, cluster.lower_bound, cluster.upper_bound, config
    )
    interactions = detect_interactions(
        zone_candles,
        cluster.kind,
        cluster.lower_bound,
        cluster.upper_bound,
        cluster.representative_price,
        config,
        stop_at=break_event.first_broken_at if break_event else None,
    )

    independent = [i for i in interactions if i.is_independent]
    interaction_summary = InteractionSummary(
        independent_touches=len(independent),
        rejections=len([i for i in independent if i.interaction_type == InteractionType.REJECTION]),
        wick_breaches=len([i for i in independent if i.interaction_type == InteractionType.WICK_BREACH]),
    )

    freshness = compute_freshness(zone_candles, interactions, break_event)
    lifecycle = determine_lifecycle(freshness, len(independent), is_broken=bool(break_event), config=config)

    bars_since_last_interaction = (
        freshness.bars_since_last_touch
        if freshness.bars_since_last_touch is not None
        else freshness.bars_since_created
    )
    strength = compute_strength(
        cluster.evidence,
        cluster.confluence.timeframe_count,
        interactions,
        bars_since_last_interaction,
        is_broken=bool(break_event),
        config=config,
    )

    price_relationship = (
        compute_price_relationship(cluster.lower_bound, cluster.upper_bound, current_price)
        if current_price is not None
        else None
    )

    return Zone(
        id=cluster.id,
        kind=cluster.kind,
        lower_bound=cluster.lower_bound,
        upper_bound=cluster.upper_bound,
        representative_price=cluster.representative_price,
        member_levels=cluster.member_levels,
        evidence=cluster.evidence,
        confluence=cluster.confluence,
        known_at=cluster.known_at,
        interactions=interactions,
        interaction_summary=interaction_summary,
        break_event=break_event,
        lifecycle=lifecycle,
        strength=strength,
        freshness=freshness,
        price_relationship=price_relationship,
    )


def _rank_by_relevance(zones: list[Zone]) -> list[Zone]:
    def relevance(zone: Zone) -> float:
        distance_percent = zone.price_relationship.distance_percent if zone.price_relationship else 0.0
        penalty = min(
            distance_percent * RELEVANCE_DISTANCE_PENALTY_PER_PERCENT, RELEVANCE_MAX_DISTANCE_PENALTY
        )
        return zone.strength.total - penalty

    return sorted(zones, key=relevance, reverse=True)
