"""Tunable thresholds for the feature engine. Nothing here is a magic number
buried in a calculation — every threshold a feature depends on is named here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureConfig:
    atr_period: int = 14

    ema_period: int = 20
    sma_medium_period: int = 50
    sma_long_period: int = 200

    rolling_windows: tuple = (5, 10, 20, 50)

    rvol_period: int = 20
    intraday_rvol_lookback_days: int = 20

    doji_body_ratio_threshold: float = 0.1


DEFAULT_FEATURE_CONFIG = FeatureConfig()
