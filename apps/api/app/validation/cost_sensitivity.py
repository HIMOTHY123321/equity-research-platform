"""Phase 15 §13/§14: ESTIMATED COST SENSITIVITY -- a research haircut
applied to already-observed raw price returns, never an actual fill
simulation. Configurable, clearly-labeled basis-point assumptions only;
this module has no concept of an order book, bid/ask, or execution."""

from __future__ import annotations

from statistics import median

from app.validation.schemas import CostSensitivityPoint

DEFAULT_COST_SCENARIOS_BPS: tuple[float, ...] = (0.0, 2.0, 5.0, 10.0, 20.0)


def apply_cost_sensitivity(
    returns_percent: list[float], scenarios_bps: tuple[float, ...] = DEFAULT_COST_SCENARIOS_BPS
) -> list[CostSensitivityPoint]:
    """`returns_percent` are already-observed raw directional returns
    (percent). Each scenario subtracts a flat round-trip cost (bps,
    converted to percent) from every return before recomputing the
    summary stats -- a labeled sensitivity analysis, not a claim about
    actual achievable P&L."""
    points: list[CostSensitivityPoint] = []
    for bps in scenarios_bps:
        cost_percent = bps / 100.0
        if not returns_percent:
            points.append(CostSensitivityPoint(cost_bps=bps))
            continue
        adjusted = [r - cost_percent for r in returns_percent]
        positive = sum(1 for r in adjusted if r > 0)
        points.append(
            CostSensitivityPoint(
                cost_bps=bps,
                median_return_after_cost=median(adjusted),
                mean_return_after_cost=sum(adjusted) / len(adjusted),
                positive_rate_after_cost=positive / len(adjusted),
            )
        )
    return points
