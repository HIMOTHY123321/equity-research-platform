"""Provider capability metadata (#2) -- inspected against real yfinance
behavior, not assumed. Static, versioned data (not a live provider ping on
every startup) so this package stays network-free in tests and CI (#51);
re-inspect and update this file by hand if yfinance's behavior changes.

Investigation performed 2026-08-25 against real SPY data via `yfinance`
(the same package/version this app depends on), using the exact call shape
`app/market_data/yfinance_provider.py` uses (`Ticker.history(period=...,
interval=..., prepost=True)`).

Two different ceilings were found for the intraday intervals, and they are
deliberately NOT conflated:

- An explicit `start=`/`end=` date range hits a hard, documented Yahoo API
  error above 730 calendar days for 1h, 60 days for 15m/5m, 8 days for 1m.
- The `period="730d"` / `period="60d"` STRING this app actually uses
  (`_YFINANCE_MAX_PERIOD` in yfinance_provider.py) empirically returned
  *more* than that -- ~1063 calendar days for 1h, ~85 for 15m/5m -- an
  undocumented quirk of yfinance's own period parsing, reproduced across
  several nearby period values, not a fluke of one request.

`max_reliable_lookback_days` below uses the conservative, documented,
explicit-range figure -- not the larger empirically-observed one -- because
research code built against the larger number would silently break the
moment yfinance's period-parsing quirk changes or the app's call shape
changes. The larger observed figure is recorded in `interval_limitations`
as a fact, not a guarantee.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.research_intelligence.schemas import ProviderCapabilityReport, ProviderTimeframeCapability

_INSPECTED_AT = datetime(2026, 8, 25, tzinfo=timezone.utc)

YFINANCE_CAPABILITY = ProviderCapabilityReport(
    provider="yfinance",
    timeframes={
        "1d": ProviderTimeframeCapability(
            timeframe="1d",
            max_reliable_lookback_days=None,
            interval_limitations=(
                "No meaningful ceiling for a mature symbol -- live-tested with period='max' and got SPY "
                "back to 1993-01-29 (8450 bars). This app's provider currently self-limits to "
                "period='10y' (_YFINANCE_MAX_PERIOD), which is an app choice, not a provider limit -- "
                "raise that if more 1D history is needed for research."
            ),
            extended_hours_supported=False,
            extended_hours_notes="Daily bars have no intraday extended-hours concept.",
            source="live_inspection",
            inspected_at=_INSPECTED_AT,
        ),
        "1h": ProviderTimeframeCapability(
            timeframe="1h",
            max_reliable_lookback_days=730,
            interval_limitations=(
                "Explicit start/end range errors above 730 calendar days ('must be within the last 730 "
                "days'). The period='730d' string this app's provider actually requests empirically "
                "returned ~1063 calendar days / ~12100 bars, reproducibly -- an undocumented yfinance "
                "period-parsing quirk, not a stable guarantee; research code should not depend on it. "
                "1H is the recommended first serious research timeframe: ~730 reliable calendar days is "
                "sufficient for a chronological dev/validation/test split with meaningful sample sizes "
                "in each partition."
            ),
            extended_hours_supported=True,
            extended_hours_notes=(
                "prepost=True required (prepost=False on a 15m/60d comparison request returned 1542 vs "
                "3742 rows). Volume is consistently 0 on extended-hours bars."
            ),
            source="live_inspection",
            inspected_at=_INSPECTED_AT,
        ),
        "15m": ProviderTimeframeCapability(
            timeframe="15m",
            max_reliable_lookback_days=60,
            interval_limitations=(
                "Explicit start/end range errors above 60 calendar days ('must be within the last 60 "
                "days'). The period='60d' string this app's provider actually requests empirically "
                "returned ~85 calendar days / ~3742 bars -- same undocumented quirk as 1h, not to be "
                "relied on. 60 reliable days is thin for chronological dev/validation/test partitioning "
                "of a lower-frequency setup type; treat 15m research conclusions as provisional until "
                "more history accumulates via repeated pulls over time."
            ),
            extended_hours_supported=True,
            extended_hours_notes="prepost=True required; volume consistently 0 on extended-hours bars.",
            source="live_inspection",
            inspected_at=_INSPECTED_AT,
        ),
        "5m": ProviderTimeframeCapability(
            timeframe="5m",
            max_reliable_lookback_days=60,
            interval_limitations=(
                "Same explicit-range ceiling as 15m (60 calendar days). period='60d' empirically "
                "returned ~85 calendar days / ~11222 bars -- same unreliable quirk, not depended on "
                "here. 60 reliable days is too thin for a serious chronological partition split; 5m "
                "should be treated as exploratory only until significantly more history accumulates."
            ),
            extended_hours_supported=True,
            extended_hours_notes="prepost=True required; volume consistently 0 on extended-hours bars.",
            source="live_inspection",
            inspected_at=_INSPECTED_AT,
        ),
    },
)


def capability_for_timeframe(timeframe: str) -> ProviderTimeframeCapability:
    try:
        return YFINANCE_CAPABILITY.timeframes[timeframe]
    except KeyError as exc:
        raise ValueError(
            f"no inspected provider capability for timeframe {timeframe!r} -- "
            f"known timeframes: {sorted(YFINANCE_CAPABILITY.timeframes)}"
        ) from exc
