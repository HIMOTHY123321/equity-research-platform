"""Gathers confirmed-swing-derived raw levels across one or more
MarketStructureSnapshots (one per source timeframe). This is what lets a
single S/R snapshot see "daily swing high" and "4H swing high" and "1H
swing high" simultaneously -- Phase 4's single "most recent active swing"
limitation does not apply here; every confirmed swing across every supplied
timeframe becomes its own independent, permanent RawLevel.
"""

from __future__ import annotations

from datetime import datetime

from app.market_structure.schemas import MarketStructureSnapshot, SwingType
from app.schemas.market_data import Timeframe
from app.support_resistance.ids import raw_level_id
from app.support_resistance.schemas import LevelKind, RawLevel


def extract_swing_levels(
    structure_snapshots: dict[Timeframe, MarketStructureSnapshot], as_of: datetime
) -> list[RawLevel]:
    levels: list[RawLevel] = []
    for timeframe, snapshot in structure_snapshots.items():
        for swing in snapshot.swings:
            if swing.confirmed_at > as_of:
                continue  # defense in depth; snapshots should already be as-of safe
            source = "confirmed_swing_high" if swing.type == SwingType.HIGH else "confirmed_swing_low"
            kind = LevelKind.RESISTANCE if swing.type == SwingType.HIGH else LevelKind.SUPPORT
            levels.append(
                RawLevel(
                    id=raw_level_id(source, timeframe, swing.pivot_timestamp),
                    price=swing.price,
                    kind=kind,
                    source=source,
                    source_timeframe=timeframe,
                    origin_timestamp=swing.pivot_timestamp,
                    known_at=swing.confirmed_at,
                    metadata={
                        "swing_classification": swing.classification.value if swing.classification else None,
                        "swing_is_broken": swing.is_broken,
                    },
                )
            )
    return levels
