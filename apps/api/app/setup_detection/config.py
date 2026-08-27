"""Every threshold and rule Phase 6 setup detection depends on, centralized
here -- detectors should read these, never hard-code a magic number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SetupDetectionConfig:
    # How far back (in completed primary-timeframe bars) detectors look for
    # brand-new candidates. Reference-level lookups (yesterday's high, a
    # confirmed swing) still use full available history regardless -- this
    # only bounds how far back a *new* candidate can be created from, which
    # keeps detection cheap and the snapshot output bounded (see #29/#40).
    detection_lookback_bars: int = 60

    # Breakout / breakdown confirmation. A close must clear the level by
    # more than this percentage; 0.0 = any strictly-beyond close counts,
    # matching the bos_tolerance_percent convention from Phase 4.
    breakout_tolerance_percent: float = 0.0

    # Breakout + retest: how close price must return to the broken level to
    # count as a genuine retest (percentage of the level's price).
    retest_tolerance_percent: float = 0.15
    retest_max_bars_after_breakout: int = 30

    # Failed breakout: a confirmed close-above that closes back inside/below
    # within this many completed bars becomes confirmed_breakout_failure
    # rather than a still-live breakout.
    failed_breakout_bars: int = 3

    # Soft-confirmation thresholds.
    min_rvol_for_confirmation: float = 1.2
    min_rvol_for_sweep: float = 1.1

    # A same-direction opposing zone within this percentage of the
    # candidate's reference price is flagged as a conflict.
    opposing_zone_proximity_percent: float = 0.5

    # Gap detection (reuses Phase 3's GapFeature -- see gap_continuation.py).
    min_gap_percent_for_continuation: float = 0.3
    gap_mostly_filled_percent: float = 80.0

    # Liquidity sweep: the wick must reverse back through the level by at
    # least this percentage to count as a genuine close-back-above/below,
    # not a marginal graze.
    sweep_reversal_tolerance_percent: float = 0.02

    # Support reclaim: how many bars back we search for "price was
    # genuinely below the level" before the reclaiming close.
    reclaim_lookback_bars: int = 20

    # Trend pullback: how close price must retrace toward active
    # support/resistance to count as "pulled back into it".
    pullback_proximity_percent: float = 0.5

    # Range breakout tolerance (percentage beyond active_range bound).
    range_breakout_tolerance_percent: float = 0.0

    # Expiration, in completed primary-timeframe bars. Different setup types
    # can override the default via the per-type map (keyed by SetupType.value).
    default_candidate_expiration_bars: int = 20
    candidate_expiration_bars_by_type: dict = field(default_factory=dict)

    # Data-quality gate: minimum completed candles required before any
    # detector is allowed to run at all (see #22).
    min_candles_required: int = 30

    # Snapshot bounding (#29) -- full detector output remains available via
    # the lower-level functions; only the assembled API-facing snapshot trims.
    max_qualified_in_snapshot: int = 15
    max_candidates_in_snapshot: int = 15
    max_rejected_in_snapshot: int = 10
    max_recently_invalidated_in_snapshot: int = 5
    max_recently_expired_in_snapshot: int = 5

    # Market-context association (#28): which benchmark symbol individual
    # equities are compared against. None disables MarketContext population
    # entirely -- deliberately not wired up in Phase 6 (see ADR 0007).
    benchmark_symbol: Optional[str] = None


DEFAULT_SETUP_DETECTION_CONFIG = SetupDetectionConfig()


def get_expiration_bars(setup_type_value: str, config: SetupDetectionConfig) -> int:
    return config.candidate_expiration_bars_by_type.get(
        setup_type_value, config.default_candidate_expiration_bars
    )
