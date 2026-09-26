"""Phase 15 §17/§39: concentration warnings for `ProspectiveObservation`
cohorts -- same philosophy as
`app.research_intelligence.concentration.detect_concentration`,
reimplemented directly against `ProspectiveObservation`'s own fields."""

from __future__ import annotations

from collections import Counter

from app.validation.schemas import ConcentrationWarning

CONCENTRATION_WARNING_SHARE = 0.5


def _share_warning(dimension: str, keys: list[str | None]) -> list[ConcentrationWarning]:
    n = len(keys)
    if n == 0:
        return []
    counts = Counter(k for k in keys if k is not None)
    if not counts:
        return []
    dominant_value, dominant_count = counts.most_common(1)[0]
    share = dominant_count / n
    if share < CONCENTRATION_WARNING_SHARE:
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


def detect_concentration(observations) -> list[ConcentrationWarning]:
    warnings: list[ConcentrationWarning] = []
    warnings += _share_warning("symbol", [o.symbol for o in observations])
    warnings += _share_warning(
        "month", [o.alert_occurred_at.strftime("%Y-%m") for o in observations]
    )
    warnings += _share_warning("setup_type", [o.setup_type for o in observations])
    warnings += _share_warning("volatility_regime", [o.volatility_regime for o in observations])
    return warnings
