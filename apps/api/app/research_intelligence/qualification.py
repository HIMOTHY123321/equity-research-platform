"""Expanded qualification lift (#15). Phase 7's
`app/research/summary.py::qualification_lift` already computes the
qualified-vs-rejected median difference per horizon -- this expands that
with sample counts, mean, effect size, MFE/MAE difference, a bootstrap
interval, baseline-adjusted difference (when a baseline is supplied), and
a dev/val/test breakdown, by delegating to the shared `compare_groups`.

`independence_adjusted_qualification_lift` (Phase 9 #18) re-runs the same
comparison at the RAW/EPISODE/PURGED levels via `conclusion_stability` and
attaches a deterministic SURVIVES/WEAKENS/DISAPPEARS/REVERSES/
INSUFFICIENT_INDEPENDENT_SAMPLE label per horizon -- the raw
`expanded_qualification_lift` result above is never replaced by this, only
supplemented, per Phase 9 #1 ("preserve Phase 8 results").
"""

from __future__ import annotations

from typing import Optional

from app.research.schemas import GroupOutcomeStats, SetupLedgerEntry
from app.research_intelligence.comparison import compare_groups
from app.research_intelligence.conclusion_stability import conclusion_stability
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import ConclusionStabilityReport, GroupComparisonResult, Partition
from app.schemas.market_data import Timeframe


def expanded_qualification_lift(
    qualified: list[SetupLedgerEntry],
    rejected: list[SetupLedgerEntry],
    horizons: tuple,
    seed: int,
    partition_by_setup_id: Optional[dict[str, Partition]] = None,
    qualified_baseline: Optional[GroupOutcomeStats] = None,
    rejected_baseline: Optional[GroupOutcomeStats] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> list[GroupComparisonResult]:
    return [
        compare_groups(
            qualified,
            rejected,
            "qualified",
            "rejected",
            horizon_bars=horizon_bars,
            seed=seed,
            partition_by_setup_id=partition_by_setup_id,
            group_a_baseline=qualified_baseline,
            group_b_baseline=rejected_baseline,
            config=config,
        )
        for horizon_bars in horizons
    ]


def independence_adjusted_qualification_lift(
    qualified: list[SetupLedgerEntry],
    rejected: list[SetupLedgerEntry],
    horizons: tuple,
    timeframe: Timeframe,
    seed: int,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> list[ConclusionStabilityReport]:
    return [
        conclusion_stability(
            qualified,
            rejected,
            group_a_label="qualified",
            group_b_label="rejected",
            finding_label="qualification lift",
            horizon_bars=horizon_bars,
            timeframe=timeframe,
            seed=seed,
            config=config,
        )
        for horizon_bars in horizons
    ]
