"""Phase 15 §23: historical (Phase 7-9 replay) vs prospective (live
monitoring) comparison for a matching cohort. The two datasets are never
combined into one estimate -- this returns both, side by side, plus a
simple rule-based agreement flag."""

from __future__ import annotations

from statistics import median
from typing import Optional

from app.research.repository import ResearchRepository
from app.validation.schemas import HistoricalProspectiveComparison, ProspectiveObservation

_HORIZON_FIELD = {1: "return_1", 3: "return_3", 5: "return_5", 10: "return_10", 20: "return_20"}


def historical_returns_for_cohort(
    research_repository: ResearchRepository,
    *,
    symbol: str,
    setup_type: str,
    direction: str,
    horizon_bars: int,
) -> list[float]:
    """Pools matching ledger entries' resolved horizon returns across
    every historical replay run. Read-only, historical-replay data only
    -- never treated as prospective (see app.validation.dataset)."""
    returns: list[float] = []
    for run in research_repository.list_runs(limit=200):
        entries = research_repository.list_ledger_entries(
            run.research_run_id, setup_type=setup_type, limit=5000
        )
        for entry in entries:
            if entry.symbol != symbol or entry.direction != direction or entry.outcome is None:
                continue
            for horizon in entry.outcome.horizons:
                if horizon.horizon_bars == horizon_bars and horizon.available:
                    if horizon.directional_return_percent is not None:
                        returns.append(horizon.directional_return_percent)
    return returns


def compare_historical_vs_prospective(
    cohort_label: str,
    historical_returns: list[float],
    prospective_observations: list[ProspectiveObservation],
    horizon_bars: int,
) -> HistoricalProspectiveComparison:
    field = _HORIZON_FIELD[horizon_bars]
    prospective_returns = [
        v for o in prospective_observations if o.resolved and (v := getattr(o, field)) is not None
    ]

    historical_median = median(historical_returns) if historical_returns else None
    prospective_median = median(prospective_returns) if prospective_returns else None

    direction_agreement: Optional[bool] = None
    magnitude_agreement: Optional[bool] = None
    note: Optional[str] = None

    if historical_median is None or prospective_median is None:
        note = "Comparison unavailable: one or both datasets have no resolved observations."
    else:
        direction_agreement = (historical_median > 0) == (prospective_median > 0)
        # Magnitude agreement: neither more than 2x the other in absolute
        # terms (a coarse, honest, rule-based check -- not a statistical test).
        lo, hi = sorted((abs(historical_median), abs(prospective_median)))
        magnitude_agreement = hi <= lo * 2 if lo > 0 else hi == 0

    return HistoricalProspectiveComparison(
        cohort_label=cohort_label,
        historical_n=len(historical_returns),
        historical_median_effect=historical_median,
        prospective_n=len(prospective_returns),
        prospective_median_effect=prospective_median,
        direction_agreement=direction_agreement,
        magnitude_agreement=magnitude_agreement,
        note=note,
    )
