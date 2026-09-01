"""Every threshold Phase 8's research-intelligence engine depends on,
centralized here -- same convention as every other engine's config.py.
"""

from __future__ import annotations

from dataclasses import dataclass

# Item #4's dataset manifest needs an app/detector version. There's no git
# commit-hash or per-package version scheme in this repo yet, so this is
# kept as a hand-synced copy of pyproject.toml's [project].version -- same
# "kept in sync by hand" convention app/research/config.py already uses for
# candle_window_by_timeframe (see docs/decisions/0008).
APP_VERSION = "0.1.0"


@dataclass(frozen=True)
class ResearchIntelligenceConfig:
    # The default research universe (#3). Never hardcoded inside a
    # detector, engine, or query -- always threaded through explicitly, and
    # always overridable by whoever calls into this package.
    default_universe_symbols: tuple = ("SPY", "QQQ", "NVDA", "AAPL", "MSFT", "META", "AMZN", "TSLA")
    default_universe_timeframe: str = "1h"

    # One consistent date-selection rule (#3): "as much history as the
    # provider reliably supports for this timeframe, ending at the most
    # recent fully-completed session" -- applied identically to every
    # symbol in a run, never widened or narrowed per-symbol to get nicer
    # results for one name.
    date_selection_rule: str = "max_reliable_provider_lookback_ending_at_last_completed_session"

    # Chronological partition ratios (#5). Must sum to 1.0; validated at
    # call time, not just trusted.
    development_ratio: float = 0.6
    validation_ratio: float = 0.2
    test_ratio: float = 0.2

    # Sample-size labels, matching app/research/config.py's existing
    # convention (#22) -- descriptive only, never a significance claim.
    small_sample_min: int = 20
    moderate_sample_min: int = 50
    larger_sample_min: int = 200

    # Bootstrap resampling (#10). Deterministic seed so tests are
    # reproducible; iteration count is a real tradeoff (accuracy vs. cost),
    # not an arbitrary round number.
    bootstrap_iterations: int = 2000
    bootstrap_confidence_level: float = 0.90

    # Below this many observations, a bootstrap interval is suppressed
    # entirely rather than shown misleadingly narrow (#10).
    bootstrap_min_sample: int = 20

    # Sample-concentration warning thresholds (#24): the max share of a
    # cohort's observations one symbol/month/episode may represent before
    # a concentration warning is attached.
    concentration_warning_share: float = 0.5

    # Signal decay pattern classification (#18) -- deliberately simple,
    # threshold-based, and fully documented in decay.py rather than a
    # fitted/learned rule. Fractions of the peak absolute median return
    # across available horizons.
    decay_immediate_threshold: float = 0.7  # earliest horizon already >= this share of peak magnitude
    decay_delayed_threshold: float = 0.3  # earliest horizon below this share of peak magnitude
    decay_persistent_threshold: float = 0.7  # latest horizon retains at least this share of peak magnitude

    # First-hit path analysis (#19/#20) default ATR thresholds -- overridable
    # per query, never hardcoded inside the analysis function itself.
    first_hit_favorable_atr: float = 1.0
    first_hit_adverse_atr: float = 1.0

    # Analog engine (#25/#26) -- centralized similarity weights. Each
    # dimension's weight is its share of the total distance contribution;
    # weights need not sum to 1.0 (the distance function normalizes), but
    # keeping them comparable in magnitude makes the breakdown legible.
    # Categorical dimensions come straight from SetupFingerprint (#19);
    # numeric dimensions are derived from SetupContext + the detection
    # candle's own close (#25's "distance to support/resistance," "MA
    # relationships," "range position") -- true ATR-normalized volatility
    # is deliberately not a separate dimension: rvol_bucket already
    # captures a volatility-adjacent categorical signal, and a clean
    # cross-symbol ATR-vs-price normalization needs plumbing this pass
    # doesn't have; documented as a known limitation, not silently guessed.
    analog_weights: dict = None  # populated below
    analog_top_n: int = 10

    # Numeric-dimension normalization: the magnitude of difference (in the
    # dimension's own units) that counts as "fully different" (contributes
    # the dimension's whole weight). Differences beyond this are capped at
    # the full weight, never allowed to dominate the whole distance.
    analog_percent_distance_scale: float = 2.0  # percentage points, for support/resistance/MA distances
    analog_confluence_scale: float = 3.0  # zone count difference
    analog_range_position_scale: float = 1.0  # already a 0..1 fraction

    # Conclusion stability labeling (Phase 9 #11/#12) -- deterministic
    # thresholds on ratio = purged_difference / raw_difference, never a
    # manually-chosen label. Documented in conclusion_stability.py.
    conclusion_reversal_ratio_threshold: float = -0.1
    conclusion_disappears_ratio_threshold: float = 0.1
    conclusion_survives_ratio_threshold: float = 0.7

    # Multiple-comparison awareness (#32): a warning attaches when a single
    # view displays at least this many simultaneous comparisons/cohorts --
    # not a correction (no p-value adjustment is applied), just a visible
    # flag that many comparisons increase the odds one looks good by chance.
    multiple_comparison_warning_threshold: int = 10

    def __post_init__(self):
        total = self.development_ratio + self.validation_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"partition ratios must sum to 1.0, got {total}")

        if self.analog_weights is None:
            object.__setattr__(
                self,
                "analog_weights",
                {
                    "setup_type": 3.0,
                    "direction": 3.0,
                    "daily_structure": 1.5,
                    "four_hour_structure": 1.5,
                    "one_hour_structure": 1.0,
                    "rvol_bucket": 1.0,
                    "gap_state": 1.0,
                    "resistance_confluence": 0.75,
                    "support_confluence": 0.75,
                    "distance_to_support_percent": 1.0,
                    "distance_to_resistance_percent": 1.0,
                    "ma20_relative_percent": 0.75,
                    "range_position": 0.75,
                    # Phase 10 (#I) -- zero-weighted dimensions contribute
                    # nothing even when populated; these are given real
                    # weight only because a caller must explicitly opt into
                    # populating them at all (extract_features's optional
                    # catalyst_context param), so their presence in this
                    # table never changes analog ranking unless catalyst
                    # context was actually requested.
                    "catalyst_category": 1.0,
                    "catalyst_recency_bucket": 0.75,
                },
            )


DEFAULT_RESEARCH_INTELLIGENCE_CONFIG = ResearchIntelligenceConfig()
