"""Every threshold Phase 12 depends on, centralized here -- same convention
as every other engine's config.py. Sample-size thresholds are deliberately
*not* redefined here: `too_few_purged_episodes` reuses
`app.research_intelligence.config.DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
.small_sample_min` directly (#reuse machinery, never duplicate).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastConfig:
    # DIRECTION (#B): a return inside this band (in percent, or in ATR
    # terms if that's larger) is FLAT/INDETERMINATE rather than UP/DOWN --
    # prevents noise-level moves from being scored as a directional call.
    direction_flat_band_min_percent: float = 0.05
    direction_flat_band_atr_fraction: float = 0.10

    # VOLATILITY (#B): ATR(horizon) vs ATR(creation) ratio thresholds.
    volatility_expansion_ratio: float = 1.10
    volatility_contraction_ratio: float = 0.90

    # SETUP_OUTCOME (#B): ATR-normalized excursion thresholds, reusing the
    # same ATR-normalized MFE/MAE convention app.research.outcomes already
    # computes -- never a price target.
    setup_outcome_favorable_atr_threshold: float = 1.0
    setup_outcome_adverse_atr_threshold: float = 1.0

    # Evidence quality (#E) / abstention (#C): overlap fraction at or above
    # this is "high overlap" for abstention purposes -- same descriptive
    # meaning app.research_intelligence.dependence.detect_overlap already
    # reports, just a decision threshold on top of it.
    high_overlap_fraction: float = 0.75

    # A market_as_of older than this, relative to the request's own real
    # "now", is treated as stale for prospective forecast creation -- the
    # mechanical enforcement behind "never backfill" (#J): the API route
    # rejects creation outside this tolerance rather than silently allowing
    # a historical market_as_of to be labeled PROSPECTIVE.
    prospective_market_as_of_tolerance_seconds: float = 300.0


DEFAULT_FORECAST_CONFIG = ForecastConfig()
