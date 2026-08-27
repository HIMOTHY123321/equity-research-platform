"""Lifecycle transition helpers (#3). Every state change carries its own
timestamp and a deterministic reason -- never backdated to the original
candidate candle. `bar_duration_seconds` comes from
app.market_structure.common.TIMEFRAME_DURATION so expiration is expressed
in real bar counts, not wall-clock time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.setup_detection.config import SetupDetectionConfig, get_expiration_bars
from app.setup_detection.schemas import LifecycleTransition, SetupLifecycleState, SetupType


def transition(
    state: SetupLifecycleState, timestamp: datetime, reason_code: str, reason_label: str
) -> LifecycleTransition:
    return LifecycleTransition(
        state=state, timestamp=timestamp, reason_code=reason_code, reason_label=reason_label
    )


def compute_expires_at(
    candidate_candle_timestamp: datetime,
    setup_type: SetupType,
    bar_duration_seconds: float,
    config: SetupDetectionConfig,
) -> datetime:
    bars = get_expiration_bars(setup_type.value, config)
    from datetime import timedelta

    return candidate_candle_timestamp + timedelta(seconds=bar_duration_seconds * bars)


def is_past_expiration(expires_at: Optional[datetime], as_of: datetime) -> bool:
    return expires_at is not None and as_of >= expires_at
