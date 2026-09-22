"""Phase 11.1 (#B): the one canonical deterministic point-in-time pipeline.

`build_market_snapshot(symbol, timeframe, provider, as_of)` composes the
exact same Phase 3-6 production functions every other entry point in this
codebase already uses (`compute_feature_snapshot` ->
`compute_market_structure_snapshot` -> `compute_support_resistance_snapshot`
-> `compute_setup_detection_snapshot`) -- no engine logic is duplicated
here. `app.api.routes.market.get_setups` (the live dashboard) and
`app.ai_analysis.evidence_packet.build_evidence_packet` (live or historical)
both call this function; "live" is simply the case where `as_of` happens to
be `datetime.now(timezone.utc)`, never a structurally different code path.

The fix this module makes over the Phase 11 original (`_market_snapshot_
bundle`, now removed): candle depth. `MarketDataProvider.get_candles(symbol,
timeframe, limit=N)` only ever returns "the latest N candles the provider
currently has" -- there is no ranged historical fetch anywhere in this
codebase (confirmed: `app.market_data.candle_cache.fetch_candles_cached`
still calls `get_candles(limit=N)` under the hood; its `requested_start`/
`requested_end` are a cache key, never an actual fetch bound). Every engine
already defensively truncates its own candles to `as_of`
(`truncate_to_as_of`), so requesting a *fixed, live-sized* limit regardless
of how historical `as_of` is means truncation can silently leave too few --
or zero -- candles before `as_of`, even though the provider may genuinely
still have that history. `_required_candle_count` below sizes the request
from `as_of`'s age instead, so the fetch actually reaches back far enough;
if the provider's own retention genuinely doesn't reach that far (real data
unavailability, not a fetch-sizing bug), the existing
FeatureStatus.INSUFFICIENT_HISTORY / SetupDetectionStatus.UNAVAILABLE
data_quality reporting already built into those engines correctly says so
-- no new "unavailable" concept was invented for this.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.api.routes.market import CANDLE_LIMIT_BY_TIMEFRAME, LEVEL_SOURCE_TIMEFRAMES
from app.features.engine import compute_feature_snapshot
from app.features.schemas import FeatureSnapshot
from app.market_data.provider import MarketDataProvider
from app.market_structure.engine import compute_market_structure_snapshot
from app.market_structure.schemas import MarketStructureSnapshot
from app.schemas.market_data import Timeframe
from app.setup_detection.engine import compute_setup_detection_snapshot
from app.setup_detection.schemas import SetupDetectionSnapshot
from app.support_resistance.engine import compute_support_resistance_snapshot
from app.support_resistance.schemas import SupportResistanceSnapshot

MARKET_SNAPSHOT_PIPELINE_VERSION = "1.0"

# Absolute ceiling on any single candle fetch, matching the ceiling
# app.api.routes.research_intelligence/_research_catalysts already use for
# historical-analysis fetches (`_FETCH_LIMIT = 50_000`) -- large enough for
# any realistic historical `as_of`, small enough that a request can never
# be effectively unbounded.
_MAX_CANDLE_FETCH = 50_000

# Approximate, deliberately-generous bar durations used only to size *how
# much* history to request -- never for aggregation or truncation (that is
# app.features.common/app.market_structure.common's job, using the real
# session-aware calendar). Calendar-time/bar-duration always overestimates
# the true bar count for a period (real markets are closed nights/weekends/
# holidays), so this can only ever over-fetch, never under-fetch.
_BAR_SECONDS: dict[Timeframe, int] = {
    Timeframe.ONE_MIN: 60,
    Timeframe.FIVE_MIN: 300,
    Timeframe.FIFTEEN_MIN: 900,
    Timeframe.ONE_HOUR: 3600,
    Timeframe.FOUR_HOUR: 14400,
    Timeframe.ONE_DAY: 86400,
}


def _required_candle_count(timeframe: Timeframe, as_of: datetime, now: datetime, base_limit: int) -> int:
    """`base_limit` (CANDLE_LIMIT_BY_TIMEFRAME) is the trailing context every
    engine needs regardless of `as_of` (SMA200, swing lookback, etc). For a
    historical `as_of`, additionally reach back by however old `as_of` is,
    in bars, so truncation still leaves `base_limit` of genuine history
    *before* it -- not zero."""
    age = now - as_of
    if age <= timedelta(0):
        return base_limit
    bar_seconds = _BAR_SECONDS.get(timeframe, 86400)
    bars_of_age = math.ceil(age.total_seconds() / bar_seconds)
    return min(base_limit + bars_of_age, _MAX_CANDLE_FETCH)


@dataclass(frozen=True)
class MarketSnapshot:
    feature_snapshot: FeatureSnapshot
    structure_by_timeframe: dict[Timeframe, MarketStructureSnapshot]
    levels_snapshot: SupportResistanceSnapshot
    setup_snapshot: SetupDetectionSnapshot
    as_of: datetime
    market_data_cutoff: Optional[datetime]
    pipeline_version: str = MARKET_SNAPSHOT_PIPELINE_VERSION


def build_market_snapshot(
    symbol: str,
    timeframe: Timeframe,
    provider: MarketDataProvider,
    as_of: datetime,
    *,
    now: Optional[datetime] = None,
) -> MarketSnapshot:
    """The canonical symbol/timeframe point-in-time pipeline: candles as of
    `as_of` -> features -> structure -> support/resistance -> setup
    detection. `now` is injectable (tests only) so candle-fetch sizing is
    reproducible; it never affects *correctness*, only how many extra bars
    get requested -- truncation to `as_of` happens identically either way.
    """
    resolved_now = now or datetime.now(timezone.utc)
    candles_by_tf: dict[Timeframe, list] = {}

    def candles(tf: Timeframe) -> list:
        if tf not in candles_by_tf:
            base_limit = CANDLE_LIMIT_BY_TIMEFRAME[tf]
            fetch_limit = _required_candle_count(tf, as_of, resolved_now, base_limit)
            fetched = provider.get_candles(symbol, tf, limit=fetch_limit)
            # Over-fetching (above) only exists to guarantee the window
            # below can actually *reach* `as_of`; the window itself is
            # trimmed to the same trailing size every other pipeline (live
            # routes, replay) uses. Without this trim, seed-dependent
            # recursive indicators (Wilder ATR, EMAs) would silently differ
            # from replay/live output for the identical `as_of` merely
            # because more history happened to be fetched to reach back
            # that far -- proven by tests/unit/ai_analysis/test_replay_
            # parity.py, which is exactly what this trim makes pass.
            #
            # Strict `<` (not the shared, `<=`-based `truncate_to_as_of`):
            # `app.research.replay.run_replay`'s own per-step window is
            # `candles_sorted[idx+1-window_limit : idx+1]`, i.e. every
            # candle strictly before the triggering candle's own
            # `candle_complete_at` instant -- for back-to-back intraday
            # bars, `candle_complete_at(idx)` exactly equals the *next*
            # candle's own timestamp, so an inclusive `<=` here would hand
            # engines one candle replay's window never included (a bar
            # that has only just started forming at the `as_of` instant
            # itself), producing a different ATR/EMA seed than replay for
            # the exact same `as_of`. This is purely a window-boundary
            # choice for parity -- every engine still independently
            # truncates defensively with its own `<=` `truncate_to_as_of`.
            visible = [c for c in fetched if c.timestamp < as_of]
            candles_by_tf[tf] = visible[-base_limit:]
        return candles_by_tf[tf]

    daily_candles = candles(Timeframe.ONE_DAY)
    primary_candles = candles(timeframe)

    feature_snapshot = compute_feature_snapshot(
        symbol=symbol,
        timeframe=timeframe,
        primary_candles=primary_candles,
        daily_candles=daily_candles,
        as_of=as_of,
    )

    structure_timeframes = set(LEVEL_SOURCE_TIMEFRAMES) | {timeframe}
    structure_by_timeframe = {
        tf: compute_market_structure_snapshot(symbol, tf, candles(tf), as_of) for tf in structure_timeframes
    }

    levels_snapshot = compute_support_resistance_snapshot(
        symbol=symbol,
        timeframe=timeframe,
        primary_candles=primary_candles,
        daily_candles=daily_candles,
        structure_snapshots=structure_by_timeframe,
        as_of=as_of,
    )

    setup_snapshot = compute_setup_detection_snapshot(
        symbol=symbol,
        timeframe=timeframe,
        candles=primary_candles,
        daily_candles=daily_candles,
        feature_snapshot=feature_snapshot,
        structure_by_timeframe=structure_by_timeframe,
        levels_snapshot=levels_snapshot,
        as_of=as_of,
    )

    return MarketSnapshot(
        feature_snapshot=feature_snapshot,
        structure_by_timeframe=structure_by_timeframe,
        levels_snapshot=levels_snapshot,
        setup_snapshot=setup_snapshot,
        as_of=as_of,
        market_data_cutoff=feature_snapshot.data_quality.latest_candle_timestamp,
    )
