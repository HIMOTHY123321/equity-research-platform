"""Requested-range validation (#25). Real yfinance history limits (see
docs/decisions/0006), empirically confirmed against live data: 1h ~730
calendar days, 15m/5m ~60 calendar days, 1d effectively unlimited. A request
outside these bounds gets a clear, explicit error -- never a silently
shortened window, since that would quietly change what a research run
actually covers without telling the caller.
"""

from __future__ import annotations

from datetime import datetime, timedelta

_YFINANCE_MAX_LOOKBACK_DAYS = {
    "1d": None,  # effectively unlimited
    "4h": 730,  # derived from 1h candles
    "1h": 730,
    "15m": 60,
    "5m": 60,
}


class InvalidReplayRangeError(ValueError):
    pass


def validate_replay_range(
    provider_name: str, timeframe: str, start_date: datetime, end_date: datetime, now: datetime
) -> None:
    if end_date <= start_date:
        raise InvalidReplayRangeError("end date must be after start date")
    if end_date > now:
        raise InvalidReplayRangeError("end date cannot be in the future")

    if provider_name != "yfinance":
        return  # limits below are yfinance-specific; other providers validate their own ranges

    max_days = _YFINANCE_MAX_LOOKBACK_DAYS.get(timeframe)
    if max_days is None:
        return

    oldest_available = now - timedelta(days=max_days)
    if start_date < oldest_available:
        raise InvalidReplayRangeError(
            f"yfinance only provides ~{max_days} days of {timeframe} history "
            f"(back to approximately {oldest_available.date()}). The requested start date "
            f"{start_date.date()} is before that -- narrow the date range rather than "
            f"silently shortening it. See docs/decisions/0006-yfinance-development-provider.md."
        )
