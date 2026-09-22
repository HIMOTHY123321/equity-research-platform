"""Shared exchange-local timestamp formatting for user-facing AI prose (#5).
Nothing shown in normal UI should ever expose a raw UTC ISO string --
`app.market_data.sessions.EXCHANGE_TZ` is the same America/New_York zone the
frontend's `formatExchangeTimestamp` converts to, so prose and the Evidence
Audit Trail always agree.
"""

from __future__ import annotations

from datetime import datetime

from app.market_data.sessions import EXCHANGE_TZ


def format_exchange_timestamp(value: datetime) -> str:
    local = value.astimezone(EXCHANGE_TZ)
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} {local.tzname()}"
