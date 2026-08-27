"""Historical replay engine (#3, #4, #32). Walks completed bars forward one
at a time and, at each step, calls the exact same deterministic pipeline the
live `/setups` endpoint calls -- never a separate/faster reimplementation of
detection logic, and never a single "compute everything across the full
history, then slice" shortcut, which is exactly the kind of vectorized
lookahead risk item #32 warns about.

Provider-independent (#26): this module only ever consumes already-fetched
`Candle` lists. It has no import of, or dependency on, any concrete
MarketDataProvider.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.features.config import DEFAULT_FEATURE_CONFIG, FeatureConfig
from app.features.engine import compute_feature_snapshot
from app.market_structure.common import candle_complete_at
from app.market_structure.config import DEFAULT_MARKET_STRUCTURE_CONFIG, MarketStructureConfig
from app.market_structure.engine import compute_market_structure_snapshot
from app.research.config import DEFAULT_RESEARCH_CONFIG, ResearchConfig
from app.research.ledger import new_ledger_entry, with_updated_lifecycle
from app.research.schemas import SetupLedgerEntry
from app.schemas.market_data import Candle, Timeframe
from app.setup_detection.config import DEFAULT_SETUP_DETECTION_CONFIG, SetupDetectionConfig
from app.setup_detection.engine import compute_setup_detection_snapshot
from app.support_resistance.config import DEFAULT_SUPPORT_RESISTANCE_CONFIG, SupportResistanceConfig
from app.support_resistance.engine import compute_support_resistance_snapshot


@dataclass(frozen=True)
class BaselineSample:
    """One replay bar's (timestamp, close, regime) -- collected as replay
    already computes structure at every step, so the baseline (#20) never
    needs a second full pass over the pipeline. `daily_trend`/`four_hour_trend`
    (Phase 8 #13) piggyback on structure replay already computes at every
    step for exactly the same reason -- a structure/regime-matched baseline
    needs the same higher-timeframe trend a setup's own context was frozen
    against, not just the primary timeframe's."""

    timestamp: datetime
    close: float
    regime: str
    daily_trend: Optional[str] = None
    four_hour_trend: Optional[str] = None


@dataclass
class ReplayResult:
    ledger_entries: list[SetupLedgerEntry]
    bars_processed: int
    runtime_seconds: float
    baseline_samples: list[BaselineSample] = field(default_factory=list)
    step_timings_ms: list[float] = field(default_factory=list)


def run_replay(
    symbol: str,
    timeframe: Timeframe,
    start_date: datetime,
    end_date: datetime,
    candles: list[Candle],
    daily_candles: list[Candle],
    four_hour_candles: list[Candle],
    research_run_id: str,
    feature_config: FeatureConfig = DEFAULT_FEATURE_CONFIG,
    structure_config: MarketStructureConfig = DEFAULT_MARKET_STRUCTURE_CONFIG,
    levels_config: SupportResistanceConfig = DEFAULT_SUPPORT_RESISTANCE_CONFIG,
    setup_config: SetupDetectionConfig = DEFAULT_SETUP_DETECTION_CONFIG,
    research_config: ResearchConfig = DEFAULT_RESEARCH_CONFIG,
) -> ReplayResult:
    started = time.monotonic()

    window_limit = research_config.candle_window_by_timeframe[timeframe.value]
    daily_window_limit = research_config.candle_window_by_timeframe[Timeframe.ONE_DAY.value]
    four_hour_window_limit = research_config.candle_window_by_timeframe[Timeframe.FOUR_HOUR.value]

    candles_sorted = sorted(candles, key=lambda c: c.timestamp)
    daily_sorted = sorted(daily_candles, key=lambda c: c.timestamp)
    four_hour_sorted = sorted(four_hour_candles, key=lambda c: c.timestamp)

    replay_steps = [
        (idx, candle)
        for idx, candle in enumerate(candles_sorted)
        if start_date <= candle.timestamp <= end_date
    ]

    ledger: dict[str, SetupLedgerEntry] = {}
    baseline_samples: list[BaselineSample] = []
    step_timings_ms: list[float] = []

    for idx, candle in replay_steps:
        step_started = time.monotonic()

        as_of = candle_complete_at(candle)

        primary_window = candles_sorted[max(0, idx + 1 - window_limit) : idx + 1]

        daily_cutoff_idx = _index_at_or_before(daily_sorted, as_of)
        daily_window = daily_sorted[max(0, daily_cutoff_idx + 1 - daily_window_limit) : daily_cutoff_idx + 1]

        four_hour_cutoff_idx = _index_at_or_before(four_hour_sorted, as_of)
        four_hour_window = four_hour_sorted[
            max(0, four_hour_cutoff_idx + 1 - four_hour_window_limit) : four_hour_cutoff_idx + 1
        ]

        feature_snapshot = compute_feature_snapshot(
            symbol, timeframe, primary_window, daily_window, as_of, feature_config
        )

        structure_by_timeframe = {
            Timeframe.ONE_DAY: compute_market_structure_snapshot(
                symbol, Timeframe.ONE_DAY, daily_window, as_of, structure_config
            ),
            Timeframe.FOUR_HOUR: compute_market_structure_snapshot(
                symbol, Timeframe.FOUR_HOUR, four_hour_window, as_of, structure_config
            ),
        }
        if timeframe not in structure_by_timeframe:
            structure_by_timeframe[timeframe] = compute_market_structure_snapshot(
                symbol, timeframe, primary_window, as_of, structure_config
            )

        levels_snapshot = compute_support_resistance_snapshot(
            symbol, timeframe, primary_window, daily_window, structure_by_timeframe, as_of, levels_config
        )

        setup_snapshot = compute_setup_detection_snapshot(
            symbol,
            timeframe,
            primary_window,
            daily_window,
            feature_snapshot,
            structure_by_timeframe,
            levels_snapshot,
            as_of,
            setup_config,
        )

        all_candidates = (
            setup_snapshot.qualified_setups
            + setup_snapshot.candidates
            + setup_snapshot.rejected_candidates
            + setup_snapshot.recently_invalidated
            + setup_snapshot.recently_expired
        )
        for candidate in all_candidates:
            if candidate.id not in ledger:
                ledger[candidate.id] = new_ledger_entry(research_run_id, candidate, as_of)
            else:
                ledger[candidate.id] = with_updated_lifecycle(ledger[candidate.id], candidate, as_of)

        baseline_samples.append(
            BaselineSample(
                timestamp=candle.timestamp,
                close=candle.close,
                regime=structure_by_timeframe[timeframe].trend.trend.value,
                daily_trend=structure_by_timeframe[Timeframe.ONE_DAY].trend.trend.value,
                four_hour_trend=structure_by_timeframe[Timeframe.FOUR_HOUR].trend.trend.value,
            )
        )

        step_timings_ms.append((time.monotonic() - step_started) * 1000)

    runtime = time.monotonic() - started
    return ReplayResult(
        ledger_entries=list(ledger.values()),
        bars_processed=len(replay_steps),
        runtime_seconds=runtime,
        baseline_samples=baseline_samples,
        step_timings_ms=step_timings_ms,
    )


def _index_at_or_before(sorted_candles: list[Candle], as_of: datetime) -> int:
    """Index of the last candle with timestamp <= as_of, or -1 if none."""
    result = -1
    for idx, candle in enumerate(sorted_candles):
        if candle.timestamp <= as_of:
            result = idx
        else:
            break
    return result
