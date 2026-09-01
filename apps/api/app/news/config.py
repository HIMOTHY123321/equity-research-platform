"""Every threshold the News/Catalyst Context engine depends on, centralized
here -- same convention as every other engine's config.py (app.features.config,
app.research.config, app.research_intelligence.config, ...).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalystConfig:
    # Event grouping (#D): a candidate article joins a growing event only if
    # it shares at least one affected symbol AND the same normalized
    # category AND its published_at falls within this many hours of the
    # event's own earliest article -- an anchored window, not "close to the
    # previous article," so a slow drip of same-topic follow-ups over days
    # cannot chain-merge into one event one hour at a time (explicitly
    # rejected by the product spec: "do not merge events merely because they
    # are close in time").
    event_grouping_window_hours: float = 12.0

    # Reaction measurement (#F), in completed primary-timeframe bars --
    # deliberately the same bar-based convention app.research.config /
    # app.research_intelligence.config already use, not literal clock
    # offsets, since the deterministic engines this reuses
    # (compute_horizon_outcomes/compute_excursion) are bar-indexed. Kept as
    # its own copy rather than importing ResearchConfig's, matching the
    # existing "each engine owns its own thresholds" convention.
    reaction_horizons_bars: tuple = (1, 3, 5, 10, 20)

    # RVOL at/around the event bar >= this multiple counts as "elevated"
    # (#F, #G) -- a plain descriptive threshold, not a significance test.
    reaction_rvol_elevated_threshold: float = 1.5

    # Setup <-> catalyst linking (#G): how far back/forward from a setup's
    # own detection instant to look for catalysts at all.
    catalyst_lookback_hours_for_setup_linking: float = 72.0
    catalyst_lookahead_hours_for_setup_linking: float = 72.0

    # A catalyst within this many minutes of the setup's own detection
    # instant is timing-ambiguous (#G): too close to say with confidence
    # whether the setup formed because of, despite, or independently of it.
    timing_ambiguous_window_minutes: float = 30.0

    # Reaction-vs-setup-direction agreement (#G): the catalyst's own initial
    # (first available horizon) directional return, expressed relative to
    # the SETUP's direction (positive = same direction as the setup).
    # Above this -> catalyst-supported; below its negation -> conflicted.
    catalyst_supported_threshold_percent: float = 0.15
    catalyst_conflicted_threshold_percent: float = -0.15

    # Reaction persistence (#G): ratio of the reaction's directional return
    # at its latest available horizon to its first available horizon.
    # >= persistent_threshold -> persisted; <= fade_threshold -> faded.
    # Same "documented threshold ratio, not a fitted rule" convention as
    # app.research_intelligence.decay's decay-pattern thresholds.
    reaction_persist_threshold_ratio: float = 0.8
    reaction_fade_threshold_ratio: float = 0.5


DEFAULT_CATALYST_CONFIG = CatalystConfig()
