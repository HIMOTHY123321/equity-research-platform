"""Sample concentration warnings (#24). A cohort dominated by one
symbol/month/volatility-regime is not broad evidence, even if its sample
count looks respectable. "Episode" concentration (the fourth dimension the
Phase 8 spec names) is deliberately not implemented as its own dimension --
there is no clean, generic definition of "one episode" at the ledger-entry
granularity that doesn't just re-derive temporal concentration under a
different name; flagging it honestly as unmeasured here is preferable to
building an ad hoc, undocumented episode-clustering heuristic.
"""

from __future__ import annotations

from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import ConcentrationWarning, SampleConcentrationReport
from app.research_intelligence.stability import bucket_label


def _share_warning(
    dimension: str, entries: list[SetupLedgerEntry], key_fn, config: ResearchIntelligenceConfig
) -> list[ConcentrationWarning]:
    n = len(entries)
    if n == 0:
        return []
    counts: dict[str, int] = {}
    for entry in entries:
        key = key_fn(entry)
        if key is None:
            continue
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return []

    dominant_value, dominant_count = max(counts.items(), key=lambda kv: kv[1])
    share = dominant_count / n
    if share < config.concentration_warning_share:
        return []
    return [
        ConcentrationWarning(
            dimension=dimension,
            dominant_value=dominant_value,
            share=share,
            warning=(
                f"{dimension.upper()}_CONCENTRATION: {share:.0%} of this cohort's {n} samples "
                f"are {dominant_value}"
            ),
        )
    ]


def detect_concentration(
    entries: list[SetupLedgerEntry], config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
) -> SampleConcentrationReport:
    warnings: list[ConcentrationWarning] = []
    warnings += _share_warning("symbol", entries, lambda e: e.symbol, config)
    warnings += _share_warning("month", entries, lambda e: bucket_label(e, "monthly"), config)
    warnings += _share_warning(
        "volatility_regime",
        entries,
        lambda e: e.detection.fingerprint.rvol_bucket if e.detection.fingerprint else None,
        config,
    )
    return SampleConcentrationReport(sample_count=len(entries), warnings=warnings)
