"""Deterministic percentage-tolerance clustering of raw levels into zones.

Clustering is purely a non-destructive VIEW: every RawLevel that enters a
zone remains fully inspectable via the returned ClusteredZone.member_levels
-- nothing is deleted or overwritten. Support and resistance levels are
never merged into the same zone (clustered separately by kind); reference
levels never enter clustering at all.

Algorithm: single-linkage on price-sorted levels of one polarity. Level i+1
merges into the current group iff it's within `cluster_tolerance_percent`
of the group's most recently added (i.e. next-lowest-priced) member --
adjacent-pair comparison, not comparison against a running average, so the
result never depends on processing order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.support_resistance.config import SupportResistanceConfig, get_source_weight
from app.support_resistance.ids import zone_id
from app.support_resistance.schemas import ConfluenceInfo, LevelKind, RawLevel, ZoneEvidenceEntry


@dataclass(frozen=True)
class ClusteredZone:
    id: str
    kind: LevelKind
    lower_bound: float
    upper_bound: float
    representative_price: float
    member_levels: list[RawLevel]
    evidence: list[ZoneEvidenceEntry]
    confluence: ConfluenceInfo
    known_at: datetime


def cluster_levels(
    levels: list[RawLevel], kind: LevelKind, config: SupportResistanceConfig
) -> list[ClusteredZone]:
    candidates = sorted((lvl for lvl in levels if lvl.kind == kind), key=lambda lvl: lvl.price)
    if not candidates:
        return []

    groups: list[list[RawLevel]] = [[candidates[0]]]
    for level in candidates[1:]:
        previous = groups[-1][-1]
        tolerance = previous.price * (config.cluster_tolerance_percent / 100)
        if level.price - previous.price <= tolerance:
            groups[-1].append(level)
        else:
            groups.append([level])

    return [_build_zone(group, kind, config) for group in groups]


def _build_zone(group: list[RawLevel], kind: LevelKind, config: SupportResistanceConfig) -> ClusteredZone:
    evidence: list[ZoneEvidenceEntry] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for level in group:
        weight = get_source_weight(level.source, level.source_timeframe, config)
        evidence.append(
            ZoneEvidenceEntry(
                source=level.source,
                source_timeframe=level.source_timeframe,
                price=level.price,
                origin_timestamp=level.origin_timestamp,
                known_at=level.known_at,
                weight=weight,
            )
        )
        weighted_sum += level.price * weight
        weight_total += weight

    representative_price = (
        weighted_sum / weight_total if weight_total > 0 else sum(lvl.price for lvl in group) / len(group)
    )

    source_types = sorted({level.source for level in group})
    timeframes = sorted({level.source_timeframe for level in group})
    confluence = ConfluenceInfo(
        source_count=len(group),
        timeframe_count=len(timeframes),
        source_types=source_types,
        timeframes=timeframes,
    )

    return ClusteredZone(
        id=zone_id(kind, [level.id for level in group]),
        kind=kind,
        lower_bound=min(level.price for level in group),
        upper_bound=max(level.price for level in group),
        representative_price=representative_price,
        member_levels=list(group),
        evidence=evidence,
        confluence=confluence,
        known_at=max(level.known_at for level in group),
    )
