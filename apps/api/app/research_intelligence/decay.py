"""Signal decay profiles (#18). At each of the standard forward horizons
(1/3/5/10/20 bars), report the cohort's directional-return distribution and
a bootstrap interval where the sample permits -- then classify the overall
shape with one of four plain descriptive labels (immediate / delayed /
persistent / decaying). This is NEVER "predictive confidence": the label is
a deterministic function of the medians already reported alongside it, not
a forecast of what happens next.
"""

from __future__ import annotations

from app.research.schemas import SetupLedgerEntry
from app.research.summary import horizon_values
from app.research_intelligence.bootstrap import bootstrap_confidence_interval
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import DecayHorizonStat, DecayPattern, SignalDecayProfile
from app.research_intelligence.statistics import sample_size_label, summarize_distribution


def signal_decay_profile(
    entries: list[SetupLedgerEntry],
    horizons: tuple,
    seed: int,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> SignalDecayProfile:
    horizon_stats: list[DecayHorizonStat] = []
    for horizon_bars in horizons:
        values = horizon_values(entries, horizon_bars)
        distribution = summarize_distribution(values)
        bootstrap = bootstrap_confidence_interval(values, "median", seed, config)
        warnings = []
        label = sample_size_label(distribution.n, config)
        if label.value in ("insufficient_sample", "small_sample"):
            warnings.append(f"{label.value.upper()}: n={distribution.n} at horizon {horizon_bars}")
        horizon_stats.append(
            DecayHorizonStat(
                horizon_bars=horizon_bars,
                distribution=distribution,
                bootstrap_interval=bootstrap,
                warnings=warnings,
            )
        )

    pattern, basis = _classify_pattern(horizon_stats, config)
    return SignalDecayProfile(horizons=horizon_stats, pattern=pattern, pattern_basis=basis)


def _classify_pattern(horizon_stats: list[DecayHorizonStat], config: ResearchIntelligenceConfig) -> tuple:
    """Deterministic rule, evaluated only over horizons with a usable
    median (n >= small_sample_min) -- an insufficient-sample horizon is
    excluded from classification, not treated as zero.

    Priority order matters: a reversal, or the magnitude fading to below
    `decay_delayed_threshold` of its peak by the latest horizon, is checked
    for DECAYING *before* IMMEDIATE -- otherwise a signal that peaks at the
    earliest horizon and then fades away entirely (the textbook "decaying"
    case) would be misread as merely "immediate" just because it started
    strong, which defeats the point of having a separate decaying label."""
    usable = [
        h
        for h in horizon_stats
        if h.distribution.median is not None and h.distribution.n >= config.small_sample_min
    ]
    if len(usable) < 2:
        return DecayPattern.INCONCLUSIVE, "fewer than 2 horizons had a usable sample (n >= small_sample_min)"

    usable = sorted(usable, key=lambda h: h.horizon_bars)
    medians = [h.distribution.median for h in usable]
    earliest, latest = medians[0], medians[-1]
    peak = max(medians, key=abs)
    peak_abs = abs(peak)

    if peak_abs == 0.0:
        return DecayPattern.INCONCLUSIVE, "every usable horizon's median directional return was exactly 0"

    e = abs(earliest) / peak_abs  # earliest horizon's share of peak magnitude
    l = abs(latest) / peak_abs  # noqa: E741 -- latest horizon's share of peak magnitude
    basis = (
        f"medians at usable horizons: {dict(zip((h.horizon_bars for h in usable), medians))}; "
        f"earliest={earliest:.4f} ({e:.0%} of peak), latest={latest:.4f} ({l:.0%} of peak), peak={peak:.4f}"
    )

    if (earliest > 0) != (latest > 0) and earliest != 0 and latest != 0:
        return DecayPattern.DECAYING, basis + " -- sign reverses between earliest and latest usable horizon"

    if l < config.decay_delayed_threshold:
        return DecayPattern.DECAYING, basis + (
            f" -- latest horizon has faded to < {config.decay_delayed_threshold:.0%} of peak magnitude"
        )

    if e >= config.decay_immediate_threshold:
        return DecayPattern.IMMEDIATE, basis + (
            f" -- earliest horizon already >= {config.decay_immediate_threshold:.0%} of peak magnitude"
        )

    if e < config.decay_delayed_threshold and l >= config.decay_persistent_threshold:
        return DecayPattern.DELAYED, basis + (
            f" -- earliest horizon < {config.decay_delayed_threshold:.0%} of peak, "
            f"but latest horizon retains >= {config.decay_persistent_threshold:.0%} of peak"
        )

    if l >= config.decay_persistent_threshold:
        return DecayPattern.PERSISTENT, basis + (
            f" -- latest horizon retains >= {config.decay_persistent_threshold:.0%} of peak magnitude"
        )

    return (
        DecayPattern.DECAYING,
        basis + " -- magnitude fades toward the later horizons without reversing sign",
    )
