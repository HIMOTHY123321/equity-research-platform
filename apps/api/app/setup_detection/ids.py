"""Deterministic identity for setup candidates -- same historical
calculation at the same `as_of` always reproduces the same ID (#24). Never a
random UUID; follows the same composite-key pattern as
app/support_resistance/ids.py.

Keyed on (symbol, setup_type, direction, timeframe, reference identity,
candidate candle timestamp) -- deliberately NOT on `current_state` or on the
`as_of` the snapshot happened to be computed at, so a candidate's ID stays
fixed across its entire lifecycle. Duplicate-signal suppression (#26) is
enforced by each detector only ever calling this once per open reference
cycle (see engine.py), not by deduplicating IDs after the fact.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.market_structure.schemas import Direction
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupType


def setup_candidate_id(
    symbol: str,
    setup_type: SetupType,
    direction: Direction,
    timeframe: Timeframe,
    reference_key: str,
    candidate_candle_timestamp: datetime,
) -> str:
    raw = "|".join(
        [
            symbol,
            setup_type.value,
            direction.value,
            timeframe.value,
            reference_key,
            candidate_candle_timestamp.isoformat(),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"setup:{setup_type.value}:{digest}"
