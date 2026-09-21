"""Phase 12.1 (#C/#D): provider capability discovery. `LiveMarketService`
picks its polling-vs-streaming strategy and its honest cadence/freshness
labeling from this, never from a hardcoded assumption about which provider
is active. A capability is a factual claim about what a provider
implementation actually does -- `quote_delay_seconds=None` means "not
measured/not guaranteed," never a silent assumption of near-zero delay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProviderCapabilities:
    # True only if the provider implementation itself pushes updates (a
    # websocket/SSE feed it subscribes to) rather than being polled by us.
    real_time_quotes: bool
    streaming_quotes: bool
    streaming_trades: bool
    streaming_bars: bool
    streaming_news: bool
    historical_intraday: bool
    # Vendor-stated or empirically-observed delay, in seconds. None means
    # unmeasured/unknown -- the live layer must never treat an unset delay
    # as "0" (that would silently claim real-time behavior no one verified).
    quote_delay_seconds: Optional[float] = None
    news_delay_seconds: Optional[float] = None
    # A conservative floor on how often this provider implementation may be
    # polled without risking rate-limiting -- this is what
    # LiveConfig.resolve_poll_interval actually schedules against; it is
    # deliberately provider-owned (only the provider truly knows its own
    # rate limits), never a single global constant.
    min_poll_interval_seconds: float = 1.0


# yfinance has no push/streaming API of any kind -- this is a fact about
# Yahoo Finance's free data surface, not a limitation of this codebase's
# implementation. `quote_delay_seconds` is left unset (None) because Yahoo
# publishes no SLA and this has never been independently measured against a
# real exchange feed; the live layer reports observed `age_seconds` instead
# of trusting a claimed number. `min_poll_interval_seconds` is set well
# above yfinance's actual rate-limit threshold (already handled defensively
# in YFinanceMarketDataProvider._history/_fast_info_price via
# YFRateLimitError retry/backoff) so routine polling doesn't trip it.
YFINANCE_CAPABILITIES = ProviderCapabilities(
    real_time_quotes=False,
    streaming_quotes=False,
    streaming_trades=False,
    streaming_bars=False,
    streaming_news=False,
    historical_intraday=True,
    quote_delay_seconds=None,
    news_delay_seconds=None,
    min_poll_interval_seconds=3.0,
)

# This implementation (app.market_data.alpaca_provider) only ever makes
# plain REST calls via httpx -- it does not open Alpaca's real websocket
# feed, even though Alpaca's platform genuinely supports one for paying
# accounts. Declared non-streaming here because capabilities describe what
# THIS implementation does, never what the vendor is theoretically capable
# of; wiring up Alpaca's actual streaming endpoint is exactly the kind of
# swap ProviderCapabilities exists to make possible without touching
# anything above this layer (see ADR 0017's migration-path section).
ALPACA_CAPABILITIES = ProviderCapabilities(
    real_time_quotes=False,
    streaming_quotes=False,
    streaming_trades=False,
    streaming_bars=False,
    streaming_news=False,
    historical_intraday=True,
    quote_delay_seconds=None,
    news_delay_seconds=None,
    min_poll_interval_seconds=1.0,
)

# Phase 12.2: Massive (massive.com) genuinely pushes trades/NBBO
# quotes/per-second aggregates over a persistent WebSocket -- unlike
# yfinance/Alpaca above, this is a real streaming_* claim, not aspirational.
# quote_delay_seconds is still left unset (None): Massive's SIP timestamp
# lets us *measure* transport latency per message (app.live.latency), which
# is more honest than repeating a vendor-stated number we haven't verified
# ourselves. min_poll_interval_seconds only governs this implementation's
# REST fallback path (get_candles/get_previous_close, and quote polling if
# no MASSIVE_API_KEY streaming access is actually available) -- see
# app.market_data.massive_provider.
MASSIVE_CAPABILITIES = ProviderCapabilities(
    real_time_quotes=True,
    streaming_quotes=True,
    streaming_trades=True,
    streaming_bars=True,
    streaming_news=False,
    historical_intraday=True,
    quote_delay_seconds=None,
    news_delay_seconds=None,
    min_poll_interval_seconds=1.0,
)
