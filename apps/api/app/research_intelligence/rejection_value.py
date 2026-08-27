"""Rejection filter value, per specific rejection reason code (#16). Phase
7's `app/research/summary.py::rejection_value` already buckets rejected
entries by failed hard-check code and compares each bucket's 5-bar median
against the qualified sample -- this expands that with sample counts (per
code, already there), effect size, MFE/MAE difference, a bootstrap
interval, and a dev/val/test breakdown, at every horizon rather than just
5 bars, by delegating to the shared `compare_groups`. An entry with
multiple failed hard checks is counted under every one of those codes
(same convention Phase 7 already established) -- never causal, purely
"what did the historical sample that failed this specific check look like."

`independence_adjusted_rejection_value` (Phase 9 #19) re-runs each code's
comparison at the RAW/EPISODE/PURGED levels via `conclusion_stability`, so
an apparent filter effect (e.g. "low RVOL filter: raw +0.30pp") can be
checked against whether it survives independence adjustment, the same way
qualification lift is (`qualification.py`).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from app.research.schemas import GroupOutcomeStats, SetupLedgerEntry
from app.research_intelligence.comparison import compare_groups
from app.research_intelligence.conclusion_stability import conclusion_stability
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import ConclusionStabilityReport, GroupComparisonResult, Partition
from app.schemas.market_data import Timeframe


def rejection_codes(rejected: list[SetupLedgerEntry]) -> dict[str, list[SetupLedgerEntry]]:
    by_code: dict[str, list[SetupLedgerEntry]] = defaultdict(list)
    for entry in rejected:
        for check in entry.detection.hard_checks:
            if not check.passed:
                by_code[check.code].append(entry)
    return dict(by_code)


def expanded_rejection_value(
    rejected: list[SetupLedgerEntry],
    qualified: list[SetupLedgerEntry],
    horizons: tuple,
    seed: int,
    partition_by_setup_id: Optional[dict[str, Partition]] = None,
    qualified_baseline: Optional[GroupOutcomeStats] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> dict[str, list[GroupComparisonResult]]:
    by_code = rejection_codes(rejected)
    return {
        code: [
            compare_groups(
                entries,
                qualified,
                code,
                "qualified",
                horizon_bars=horizon_bars,
                seed=seed,
                partition_by_setup_id=partition_by_setup_id,
                group_b_baseline=qualified_baseline,
                config=config,
            )
            for horizon_bars in horizons
        ]
        for code, entries in sorted(by_code.items())
    }


def independence_adjusted_rejection_value(
    rejected: list[SetupLedgerEntry],
    qualified: list[SetupLedgerEntry],
    horizons: tuple,
    timeframe: Timeframe,
    seed: int,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> dict[str, list[ConclusionStabilityReport]]:
    by_code = rejection_codes(rejected)
    return {
        code: [
            conclusion_stability(
                entries,
                qualified,
                group_a_label=code,
                group_b_label="qualified",
                finding_label=f"rejection value: {code}",
                horizon_bars=horizon_bars,
                timeframe=timeframe,
                seed=seed,
                config=config,
            )
            for horizon_bars in horizons
        ]
        for code, entries in sorted(by_code.items())
    }
