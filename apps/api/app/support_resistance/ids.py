"""Deterministic identity for raw levels and zones.

Level IDs are composite keys derived from (source, timeframe, origin
timestamp) -- never random UUIDs. The same historical data, recomputed at
any later time, always produces the same level ID. Zone IDs are a short
hash of their sorted member level IDs, so a zone's identity is a pure
function of which evidence it contains -- add/remove a member and the ID
changes, which is the correct behavior since it's a structurally different
zone.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.schemas.market_data import Timeframe
from app.support_resistance.schemas import LevelKind


def raw_level_id(source: str, source_timeframe: Timeframe, origin_timestamp: datetime) -> str:
    return f"{source}|{source_timeframe.value}|{origin_timestamp.isoformat()}"


def zone_id(kind: LevelKind, member_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(sorted(member_ids)).encode("utf-8")).hexdigest()[:16]
    return f"zone:{kind.value}:{digest}"
