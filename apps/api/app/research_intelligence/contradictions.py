"""Research contradictions (#17). Predefined assumptions already encoded
in the product (never automatically mined) checked against observed data
using the same `compare_groups` primitive #15/#16 already use. Finding a
contradiction here never modifies detector rules automatically -- it only
surfaces the finding for a human to act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from app.market_structure.schemas import Direction
from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.comparison import compare_groups
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import ContradictionResult, ContradictionStatus, Partition


@dataclass(frozen=True)
class ResearchAssumption:
    code: str
    description: str
    group_a_label: str  # the side the assumption claims performs *better*
    group_b_label: str
    group_a_predicate: Callable[[SetupLedgerEntry], bool]
    group_b_predicate: Callable[[SetupLedgerEntry], bool]


def _daily_aligned(entry: SetupLedgerEntry) -> bool:
    fp = entry.detection.fingerprint
    if fp is None or fp.daily_structure is None:
        return False
    expected = "bullish" if entry.detection.direction == Direction.BULLISH else "bearish"
    return fp.daily_structure.value == expected


def _daily_opposed(entry: SetupLedgerEntry) -> bool:
    fp = entry.detection.fingerprint
    if fp is None or fp.daily_structure is None:
        return False
    opposing = "bearish" if entry.detection.direction == Direction.BULLISH else "bullish"
    return fp.daily_structure.value == opposing


def _rvol_confirmed(entry: SetupLedgerEntry, threshold: float = 1.5) -> bool:
    context = entry.detection.context
    return context is not None and context.rvol is not None and context.rvol >= threshold


def _rvol_not_confirmed(entry: SetupLedgerEntry, threshold: float = 1.5) -> bool:
    context = entry.detection.context
    return context is not None and context.rvol is not None and context.rvol < threshold


def _confluent(entry: SetupLedgerEntry, threshold: int = 2) -> bool:
    fp = entry.detection.fingerprint
    return fp is not None and (fp.support_confluence + fp.resistance_confluence) >= threshold


def _not_confluent(entry: SetupLedgerEntry, threshold: int = 2) -> bool:
    fp = entry.detection.fingerprint
    return fp is not None and (fp.support_confluence + fp.resistance_confluence) < threshold


def _breakout_qualified(entry: SetupLedgerEntry) -> bool:
    return entry.setup_type == "breakout_retest" and entry.detection.current_state == "qualified"


def _breakout_rejected(entry: SetupLedgerEntry) -> bool:
    return entry.setup_type == "breakout_retest" and entry.detection.current_state == "rejected"


BUILTIN_ASSUMPTIONS: tuple[ResearchAssumption, ...] = (
    ResearchAssumption(
        code="higher_timeframe_alignment_helps",
        description="Higher-timeframe (daily) structure alignment improves outcomes.",
        group_a_label="daily_aligned",
        group_b_label="daily_opposed",
        group_a_predicate=_daily_aligned,
        group_b_predicate=_daily_opposed,
    ),
    ResearchAssumption(
        code="rvol_confirmation_helps",
        description="RVOL confirmation (>=1.5x) at detection time improves outcomes.",
        group_a_label="rvol_confirmed",
        group_b_label="rvol_not_confirmed",
        group_a_predicate=_rvol_confirmed,
        group_b_predicate=_rvol_not_confirmed,
    ),
    ResearchAssumption(
        code="sr_confluence_helps",
        description="Multi-timeframe support/resistance confluence (>=2 zones) improves outcomes.",
        group_a_label="confluent",
        group_b_label="not_confluent",
        group_a_predicate=_confluent,
        group_b_predicate=_not_confluent,
    ),
    ResearchAssumption(
        code="qualification_improves_breakout_behavior",
        description="Qualified breakout_retest candidates outperform rejected breakout_retest candidates.",
        group_a_label="breakout_qualified",
        group_b_label="breakout_rejected",
        group_a_predicate=_breakout_qualified,
        group_b_predicate=_breakout_rejected,
    ),
)


def check_assumption(
    assumption: ResearchAssumption,
    entries: list[SetupLedgerEntry],
    horizon_bars: int,
    seed: int,
    partition_by_setup_id: Optional[dict[str, Partition]] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> ContradictionResult:
    group_a = [e for e in entries if assumption.group_a_predicate(e)]
    group_b = [e for e in entries if assumption.group_b_predicate(e)]

    comparison = compare_groups(
        group_a,
        group_b,
        assumption.group_a_label,
        assumption.group_b_label,
        horizon_bars=horizon_bars,
        seed=seed,
        partition_by_setup_id=partition_by_setup_id,
        config=config,
    )

    if comparison.median_difference is None:
        status = ContradictionStatus.INSUFFICIENT_DATA
    elif comparison.median_difference > 0:
        status = ContradictionStatus.SUPPORTED
    else:
        status = ContradictionStatus.NOT_SUPPORTED

    return ContradictionResult(
        assumption_code=assumption.code,
        description=assumption.description,
        group_a_label=assumption.group_a_label,
        group_b_label=assumption.group_b_label,
        comparison=comparison,
        status=status,
    )


def check_all_builtin_assumptions(
    entries: list[SetupLedgerEntry],
    horizon_bars: int,
    seed: int,
    partition_by_setup_id: Optional[dict[str, Partition]] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> list[ContradictionResult]:
    return [
        check_assumption(assumption, entries, horizon_bars, seed, partition_by_setup_id, config)
        for assumption in BUILTIN_ASSUMPTIONS
    ]
