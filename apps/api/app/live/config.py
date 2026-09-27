"""Phase 12.1 (#B/#F): all live-engine thresholds/cadences in one place, same
convention every other engine's config.py follows. Every threshold here is a
config value, not a magic number scattered through app/live/*.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FreshnessState(str, Enum):
    """(#F) Deterministic, never a judgment call -- see
    classify_freshness. A UI showing anything other than LIVE must say so;
    stale data is never left on screen looking current."""

    LIVE = "live"
    RECENT = "recent"
    DELAYED = "delayed"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    UNAVAILABLE = "unavailable"
    MARKET_CLOSED = "market_closed"


class LiveSessionState(str, Enum):
    """(#S) A display-purpose session classification distinct from
    app.schemas.market_data.MarketSession (which classifies a historical
    *candle* and has no concept of "closed" since closed days simply have
    no candles). This one answers "should the user expect updates right
    now," which weekends/closed days genuinely change."""

    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    MARKET_CLOSED = "market_closed"


class SubscriptionPriority(str, Enum):
    """(#N) Priority tiers the poll scheduler consults when deciding which
    symbol gets the shortest interval within provider rate limits -- never
    "whichever subscribed first"."""

    VIEWED = "viewed"
    ACTIVE_FORECAST = "active_forecast"
    WATCHLIST = "watchlist"
    BACKGROUND_BENCHMARK = "background_benchmark"


@dataclass(frozen=True)
class LiveConfig:
    # (#B) Aspirational target -- only actually scheduled at this cadence
    # when the active provider's ProviderCapabilities allow it (streaming,
    # or a low enough min_poll_interval_seconds); yfinance never reaches
    # this in practice and the poll loop uses the provider's own floor
    # instead (see resolve_poll_interval).
    target_interval_seconds: float = 1.0

    # (#F) age_seconds thresholds -- inclusive upper bounds per state.
    live_max_age_seconds: float = 5.0
    recent_max_age_seconds: float = 30.0
    delayed_max_age_seconds: float = 120.0
    # Beyond delayed_max_age_seconds the state is STALE.

    # (#N) Poll interval multiplier per priority tier, applied on top of the
    # provider's own min_poll_interval_seconds floor -- the viewed ticker
    # polls at the provider's true floor; lower-priority tiers back off
    # further so a large watchlist/benchmark universe can't starve the
    # symbol the user is actually looking at or trip provider rate limits.
    priority_interval_multiplier: dict[SubscriptionPriority, float] = None  # set in __post_init__

    heartbeat_interval_seconds: float = 15.0
    reconnect_initial_backoff_seconds: float = 1.0
    reconnect_max_backoff_seconds: float = 30.0
    reconnect_backoff_multiplier: float = 2.0

    # (#K) How often the background forecast monitor scans ACTIVE
    # prospective forecasts for a horizon that may have closed. Coarser
    # than quote polling on purpose -- resolution only needs to happen
    # once a horizon genuinely closes, not every second.
    forecast_monitor_interval_seconds: float = 15.0

    # (#L) News/catalyst poll interval -- yfinance's news surface has no
    # streaming option either (app.news.yfinance_provider), so this is a
    # provider-safe poll floor, not a claimed real-time feed.
    news_monitor_interval_seconds: float = 60.0

    # Phase 17 (§18/§44): gap-fill on reconnect only fires for a genuine
    # outage -- a fast blip-and-recover (the common case, sub-second) never
    # touches REST at all, since the streaming path is deliberately never
    # supposed to poll under normal operation (see LiveMarketService
    # docstring). Only a disconnect this long or longer triggers a REST
    # historical backfill of the missed, fully-CLOSED bars.
    gap_fill_min_gap_seconds: float = 5.0
    # How many of the most recent REST candles to fetch per (symbol,
    # timeframe) when backfilling -- bounded, never "however many bars the
    # gap implies," so a very long outage still costs one bounded REST call.
    gap_fill_lookback_bars: int = 20

    def __post_init__(self) -> None:
        if self.priority_interval_multiplier is None:
            object.__setattr__(
                self,
                "priority_interval_multiplier",
                {
                    SubscriptionPriority.VIEWED: 1.0,
                    SubscriptionPriority.ACTIVE_FORECAST: 2.0,
                    SubscriptionPriority.WATCHLIST: 4.0,
                    SubscriptionPriority.BACKGROUND_BENCHMARK: 10.0,
                },
            )


DEFAULT_LIVE_CONFIG = LiveConfig()


def resolve_poll_interval(
    min_poll_interval_seconds: float,
    priority: SubscriptionPriority,
    config: LiveConfig = DEFAULT_LIVE_CONFIG,
) -> float:
    """(#B/#D/#N) The actual scheduled interval for one symbol subscription
    -- never faster than the provider's own honest floor
    (ProviderCapabilities.min_poll_interval_seconds), scaled up for
    lower-priority tiers. This is the one function that turns "1 second is
    the target" into "here is what we can truthfully deliver.\""""
    floor = max(min_poll_interval_seconds, config.target_interval_seconds)
    return floor * config.priority_interval_multiplier[priority]


def classify_freshness(
    age_seconds: float | None,
    *,
    connected: bool,
    session: LiveSessionState,
    config: LiveConfig = DEFAULT_LIVE_CONFIG,
) -> FreshnessState:
    """(#F) The one, deterministic freshness classifier -- every live data
    object's freshness_state comes from this function, never an ad hoc
    per-component judgment call."""
    if not connected:
        return FreshnessState.DISCONNECTED
    if session == LiveSessionState.MARKET_CLOSED:
        return FreshnessState.MARKET_CLOSED
    if age_seconds is None:
        return FreshnessState.UNAVAILABLE
    if age_seconds <= config.live_max_age_seconds:
        return FreshnessState.LIVE
    if age_seconds <= config.recent_max_age_seconds:
        return FreshnessState.RECENT
    if age_seconds <= config.delayed_max_age_seconds:
        return FreshnessState.DELAYED
    return FreshnessState.STALE
