"""Conclusion stability (Phase 9 #11/#12). A raw group-vs-group finding
(e.g. "qualified vs rejected" or "HTF aligned vs opposed") is re-evaluated
at three levels of dependence adjustment -- RAW (every ledger entry, Phase
8's behavior), EPISODE-LEVEL (one representative per `SetupEpisode`), and
PURGED (this horizon's non-overlapping greedy selection, `independence.py`)
-- then labeled by a single deterministic rule comparing the purged
median difference against the raw one. The label is never hand-picked:

    ratio = purged_median_difference / raw_median_difference

    ratio < conclusion_reversal_ratio_threshold        -> REVERSES
    ratio <= conclusion_disappears_ratio_threshold      -> DISAPPEARS
    ratio < conclusion_survives_ratio_threshold         -> WEAKENS
    otherwise                                           -> SURVIVES

with an early INSUFFICIENT_INDEPENDENT_SAMPLE exit whenever the purged
sample is too small on either side to trust a ratio at all, matching the
Phase 8 `decay.py` convention of excluding sub-minimum horizons from
classification rather than treating them as zero. Worked example (HTF
alignment, Phase 8's raw finding): raw shows aligned underperforming
opposed by a real margin; purged shrinks that margin to near nothing
because most "aligned" and "opposed" observations shared the same few
underlying trend moves -- ratio near 0 -> DISAPPEARS, i.e. "the raw
contradiction does not survive independence adjustment."
"""

from __future__ import annotations

from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.comparison import compare_groups
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.episodes import build_episodes
from app.research_intelligence.independence import episode_level_sample, purged_sample
from app.research_intelligence.schemas import (
    ConclusionLabel,
    ConclusionStabilityReport,
    GroupComparisonResult,
)
from app.schemas.market_data import Timeframe


def conclusion_stability(
    group_a: list[SetupLedgerEntry],
    group_b: list[SetupLedgerEntry],
    group_a_label: str,
    group_b_label: str,
    finding_label: str,
    horizon_bars: int,
    timeframe: Timeframe,
    seed: int,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> ConclusionStabilityReport:
    pooled = [*group_a, *group_b]
    episodes = build_episodes(pooled)
    representatives = episode_level_sample(pooled, episodes)
    a_ids = {e.setup_id for e in group_a}
    episode_a = [e for e in representatives if e.setup_id in a_ids]
    episode_b = [e for e in representatives if e.setup_id not in a_ids]

    purged_a = purged_sample(group_a, horizon_bars, timeframe)
    purged_b = purged_sample(group_b, horizon_bars, timeframe)

    raw_result = compare_groups(
        group_a, group_b, group_a_label, group_b_label, horizon_bars, seed, config=config
    )
    episode_result = compare_groups(
        episode_a, episode_b, group_a_label, group_b_label, horizon_bars, seed, config=config
    )
    purged_result = compare_groups(
        purged_a, purged_b, group_a_label, group_b_label, horizon_bars, seed, config=config
    )

    label, basis = _classify_stability(raw_result, purged_result, config)

    return ConclusionStabilityReport(
        finding_label=finding_label,
        horizon_bars=horizon_bars,
        raw=raw_result,
        episode=episode_result,
        purged=purged_result,
        label=label,
        label_basis=basis,
    )


def _classify_stability(
    raw: GroupComparisonResult, purged: GroupComparisonResult, config: ResearchIntelligenceConfig
) -> tuple:
    a_n = purged.group_a_distribution.n
    b_n = purged.group_b_distribution.n
    if a_n < config.small_sample_min or b_n < config.small_sample_min:
        return (
            ConclusionLabel.INSUFFICIENT_INDEPENDENT_SAMPLE,
            f"purged sample too small to classify: group_a_n={a_n}, group_b_n={b_n} "
            f"(minimum {config.small_sample_min} per group)",
        )

    raw_diff = raw.median_difference
    purged_diff = purged.median_difference
    if raw_diff is None or purged_diff is None:
        return (
            ConclusionLabel.INSUFFICIENT_INDEPENDENT_SAMPLE,
            "raw or purged median difference unavailable",
        )
    if raw_diff == 0.0:
        return (
            ConclusionLabel.INSUFFICIENT_INDEPENDENT_SAMPLE,
            "raw median difference is exactly 0.0 -- stability ratio is undefined",
        )

    ratio = purged_diff / raw_diff
    basis = f"ratio = purged_difference / raw_difference = {purged_diff:.4f} / {raw_diff:.4f} = {ratio:.2f}"

    if ratio < config.conclusion_reversal_ratio_threshold:
        return ConclusionLabel.REVERSES, basis
    if ratio <= config.conclusion_disappears_ratio_threshold:
        return ConclusionLabel.DISAPPEARS, basis
    if ratio < config.conclusion_survives_ratio_threshold:
        return ConclusionLabel.WEAKENS, basis
    return ConclusionLabel.SURVIVES, basis
