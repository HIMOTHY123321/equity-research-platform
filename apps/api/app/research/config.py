"""Every threshold Phase 7 depends on, centralized here -- same convention
as every other engine's config.py."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchConfig:
    # Forward horizons, in completed primary-timeframe bars (#9).
    forward_horizons: tuple = (1, 3, 5, 10, 20)

    # How close price must return to a setup's reference level to count as
    # a retest for the structural-event outcome (#15).
    retest_tolerance_percent: float = 0.15

    # Sample-size labels (#22) -- descriptive only, never a significance claim.
    small_sample_min: int = 20
    moderate_sample_min: int = 50
    larger_sample_min: int = 200

    # Regime-matched baseline (#20): only bother forming a regime baseline
    # bucket once it has at least this many eligible timestamps.
    min_baseline_bucket_size: int = 20

    # Replay: how many primary-timeframe candles are visible to the pipeline
    # at each historical step -- must match CANDLE_LIMIT_BY_TIMEFRAME in
    # api/routes/market.py exactly, or replay would see a different amount
    # of history than the live endpoint and could disagree with it (#4).
    # Kept as its own copy (not imported) so this package never depends on
    # the api layer -- see docs/decisions/0008.
    candle_window_by_timeframe: dict = None  # populated below

    def __post_init__(self):
        if self.candle_window_by_timeframe is None:
            object.__setattr__(
                self,
                "candle_window_by_timeframe",
                {
                    "1d": 300,
                    "4h": 300,
                    "1h": 2000,
                    "15m": 4000,
                    "5m": 12000,
                },
            )


DEFAULT_RESEARCH_CONFIG = ResearchConfig()
