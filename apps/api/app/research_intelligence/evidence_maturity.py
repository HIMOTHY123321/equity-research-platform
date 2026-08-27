"""Evidence maturity (Phase 9 #24). A single categorical summary of
everything else this package already computes -- INSUFFICIENT / PRELIMINARY
/ MIXED / REPLICATED -- built ONLY because every input it needs (purged
sample size, walk-forward stability, conclusion stability, cross-symbol
replication, evidence-quality flags) now genuinely exists from earlier
Phase 9 work. This is explicitly NOT a confidence score: it is a label,
computed by a fixed, ordered checklist, never a weighted or fitted
combination of its inputs.

Checked in this exact priority order (first match wins, mirroring
`decay.py`'s "priority order matters" convention):

1. INSUFFICIENT -- the purged sample (the strictest independence view) has
   fewer than `small_sample_min` observations. Nothing below this line can
   be trusted regardless of how good it looks at the raw level.
2. MIXED -- a `ConclusionStabilityReport` was supplied and its label is
   WEAKENS, DISAPPEARS, or REVERSES: the raw and independence-adjusted
   views of this exact finding disagree. This is checked before REPLICATED
   on purpose -- a large purged sample does not excuse a conclusion that
   falls apart under its own independence adjustment.
3. REPLICATED -- every one of the following holds:
   - purged sample >= `moderate_sample_min` (stronger than the bare
     INSUFFICIENT bar above)
   - walk-forward stability is STABLE
   - every symbol with data agrees in sign (`symbols_positive ==
     symbol_coverage_count`, and there are at least 2 symbols) -- "one
     symbol's history repeating itself" is not replication
   - if a `ConclusionStabilityReport` was supplied, its label is SURVIVES
   - none of the flags that specifically indicate a fragile independence
     picture are present (HIGH_OVERLAP, LOW_INDEPENDENT_SAMPLE,
     EPISODE_CONCENTRATION, WALK_FORWARD_INSTABILITY, SINGLE_SYMBOL_
     DEPENDENCE, BLOCK_BOOTSTRAP_INCLUDES_ZERO, TEMPORAL_INSTABILITY)
4. PRELIMINARY -- everything that reaches this point: a purged sample big
   enough to look at, and not internally contradictory, but short of the
   full replication bar above.
"""

from __future__ import annotations

from typing import Optional

from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import (
    ConclusionLabel,
    ConclusionStabilityReport,
    EvidenceMaturity,
    EvidenceQualityFlag,
    ResearchEvidenceCard,
)

_FRAGILE_FLAGS = frozenset(
    {
        EvidenceQualityFlag.HIGH_OVERLAP,
        EvidenceQualityFlag.LOW_INDEPENDENT_SAMPLE,
        EvidenceQualityFlag.EPISODE_CONCENTRATION,
        EvidenceQualityFlag.WALK_FORWARD_INSTABILITY,
        EvidenceQualityFlag.SINGLE_SYMBOL_DEPENDENCE,
        EvidenceQualityFlag.BLOCK_BOOTSTRAP_INCLUDES_ZERO,
        EvidenceQualityFlag.TEMPORAL_INSTABILITY,
    }
)


def classify_evidence_maturity(
    card: ResearchEvidenceCard,
    conclusion_stability_report: Optional[ConclusionStabilityReport] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> tuple[EvidenceMaturity, str]:
    purged_n = card.purged_sample_count

    if purged_n is None or purged_n < config.small_sample_min:
        return (
            EvidenceMaturity.INSUFFICIENT,
            f"purged sample count ({purged_n}) is below small_sample_min ({config.small_sample_min})",
        )

    if conclusion_stability_report is not None and conclusion_stability_report.label in (
        ConclusionLabel.WEAKENS,
        ConclusionLabel.DISAPPEARS,
        ConclusionLabel.REVERSES,
    ):
        return (
            EvidenceMaturity.MIXED,
            f"conclusion stability label is {conclusion_stability_report.label.value} -- the raw and "
            "independence-adjusted views of this finding disagree",
        )

    cross_symbol_agrees = (
        card.symbol_coverage_count >= 2 and card.symbols_positive == card.symbol_coverage_count
    )
    conclusion_survives = conclusion_stability_report is None or (
        conclusion_stability_report.label == ConclusionLabel.SURVIVES
    )
    fragile = _FRAGILE_FLAGS.intersection(card.flags)

    if (
        purged_n >= config.moderate_sample_min
        and card.walk_forward_stability == "stable"
        and cross_symbol_agrees
        and conclusion_survives
        and not fragile
    ):
        return (
            EvidenceMaturity.REPLICATED,
            f"purged n={purged_n} >= moderate_sample_min, walk-forward stable, "
            f"{card.symbols_positive}/{card.symbol_coverage_count} symbols agree in sign, "
            "conclusion stability survives (or was not checked), no fragile-independence flags",
        )

    reasons = []
    if purged_n < config.moderate_sample_min:
        reasons.append(f"purged n={purged_n} < moderate_sample_min ({config.moderate_sample_min})")
    if card.walk_forward_stability != "stable":
        reasons.append(f"walk-forward stability is {card.walk_forward_stability}")
    if not cross_symbol_agrees:
        reasons.append(f"only {card.symbols_positive}/{card.symbol_coverage_count} symbols agree in sign")
    if not conclusion_survives:
        reasons.append(f"conclusion stability label is {conclusion_stability_report.label.value}")
    if fragile:
        reasons.append(f"fragile-independence flags present: {sorted(f.value for f in fragile)}")

    return (EvidenceMaturity.PRELIMINARY, "does not yet meet the REPLICATED bar: " + "; ".join(reasons))
