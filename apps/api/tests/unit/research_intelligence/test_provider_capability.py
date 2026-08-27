import pytest

from app.research_intelligence.provider_capability import YFINANCE_CAPABILITY, capability_for_timeframe


def test_1h_is_the_recommended_first_research_timeframe_with_a_real_lookback():
    cap = capability_for_timeframe("1h")
    assert cap.max_reliable_lookback_days == 730
    assert cap.source == "live_inspection"


def test_daily_has_no_reliable_lookback_ceiling():
    cap = capability_for_timeframe("1d")
    assert cap.max_reliable_lookback_days is None


def test_intraday_lookback_uses_the_conservative_documented_figure_not_the_observed_quirk():
    # The larger period-string-quirk figures (~1063d for 1h, ~85d for 15m/5m)
    # must never leak into max_reliable_lookback_days -- research code should
    # never silently depend on an undocumented yfinance parsing behavior.
    for timeframe, conservative_days in (("1h", 730), ("15m", 60), ("5m", 60)):
        cap = capability_for_timeframe(timeframe)
        assert cap.max_reliable_lookback_days == conservative_days


def test_every_intraday_timeframe_requires_prepost_for_extended_hours():
    for timeframe in ("1h", "15m", "5m"):
        cap = capability_for_timeframe(timeframe)
        assert cap.extended_hours_supported is True


def test_unknown_timeframe_is_rejected_explicitly_not_silently_shortened():
    with pytest.raises(ValueError, match="no inspected provider capability"):
        capability_for_timeframe("1w")


def test_report_covers_every_timeframe_this_app_actually_requests():
    # 4h is deliberately absent -- it's aggregated from 1h, not fetched directly.
    assert set(YFINANCE_CAPABILITY.timeframes) == {"1d", "1h", "15m", "5m"}
