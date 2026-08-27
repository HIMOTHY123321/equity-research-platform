"""Every threshold market-structure detection depends on, named here rather
than scattered as magic numbers through swings/classification/breaks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketStructureConfig:
    # Pivot/fractal swing detection: bars required on each side of a candidate.
    left_bars: int = 2
    right_bars: int = 2

    # HH/HL/LH/LL vs EH/EL: percentage distance within which two swings of the
    # same type are considered equal rather than higher/lower.
    equal_tolerance_percent: float = 0.1

    # A close must exceed the broken level by more than this percentage to
    # count as a confirmed break. 0.0 = any strictly-beyond close counts;
    # exact equality never counts (see ADR).
    bos_tolerance_percent: float = 0.0
    choch_tolerance_percent: float = 0.0

    # How many of the most recent classified swings inform trend/CHOCH state.
    structure_lookback_swings: int = 4

    # Evidence-count thresholds for trend strength (see classification.py).
    established_evidence_count: int = 3
    developing_evidence_count: int = 2

    # Snapshot size limits (full history still available via lower-level calls).
    max_swings_in_snapshot: int = 20
    max_events_in_snapshot: int = 10


DEFAULT_MARKET_STRUCTURE_CONFIG = MarketStructureConfig()
