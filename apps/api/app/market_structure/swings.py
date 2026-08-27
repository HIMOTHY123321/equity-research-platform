"""Pivot/fractal swing detection with an explicit pivot_timestamp/confirmed_at
split — the core lookahead-safety mechanism of this whole package.

A candidate at index i needs `right_bars` complete candles after it before
the pivot rule can be fully evaluated. Until then it is only a
CandidatePivot (no confirmed_at, never returned as structure). Once fully
evaluable, it's either a confirmed SwingPoint or not a swing at all — never
something that becomes retroactively "un-confirmed" later, since the rule
was already fully checked against real data the first time it was evaluable.

Tie convention (equal highs/lows within the pivot window): the earliest
(leftmost) candle at the extreme value wins. Left-side bars must be
STRICTLY worse than the candidate; right-side bars may TIE (since the
candidate, being earlier, already wins that tie). This is implemented as
asymmetric strict/non-strict comparisons rather than a separate tie-break
pass — see the ADR for the worked example.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.market_structure.common import candle_complete_at
from app.market_structure.config import MarketStructureConfig
from app.market_structure.schemas import CandidatePivot, SwingPoint, SwingType
from app.schemas.market_data import Candle


@dataclass(frozen=True)
class SwingDetectionResult:
    confirmed: list[SwingPoint] = field(default_factory=list)
    candidates: list[CandidatePivot] = field(default_factory=list)


def _is_pivot_high(candles: list[Candle], i: int, left: int, right: int) -> bool:
    pivot = candles[i].high
    for j in range(i - left, i):
        if candles[j].high >= pivot:
            return False
    for j in range(i + 1, i + right + 1):
        if candles[j].high > pivot:
            return False
    return True


def _is_pivot_low(candles: list[Candle], i: int, left: int, right: int) -> bool:
    pivot = candles[i].low
    for j in range(i - left, i):
        if candles[j].low <= pivot:
            return False
    for j in range(i + 1, i + right + 1):
        if candles[j].low < pivot:
            return False
    return True


def _looks_like_candidate_high(candles: list[Candle], i: int, left: int, available_right: int) -> bool:
    pivot = candles[i].high
    for j in range(i - left, i):
        if candles[j].high >= pivot:
            return False
    for j in range(i + 1, i + 1 + available_right):
        if candles[j].high > pivot:
            return False
    return True


def _looks_like_candidate_low(candles: list[Candle], i: int, left: int, available_right: int) -> bool:
    pivot = candles[i].low
    for j in range(i - left, i):
        if candles[j].low <= pivot:
            return False
    for j in range(i + 1, i + 1 + available_right):
        if candles[j].low < pivot:
            return False
    return True


def detect_swings(candles: list[Candle], config: MarketStructureConfig) -> SwingDetectionResult:
    """`candles` must already be restricted to fully-completed bars — see
    app.market_structure.common.completed_only. This function never touches
    a still-forming candle, confirmed or candidate.
    """
    left, right = config.left_bars, config.right_bars
    n = len(candles)
    confirmed: list[SwingPoint] = []
    candidates: list[CandidatePivot] = []

    for i in range(left, n):
        available_right = n - 1 - i

        if available_right >= right:
            confirmed_at = candle_complete_at(candles[i + right])
            if _is_pivot_high(candles, i, left, right):
                confirmed.append(
                    SwingPoint(
                        type=SwingType.HIGH,
                        price=candles[i].high,
                        pivot_timestamp=candles[i].timestamp,
                        confirmed_at=confirmed_at,
                        left_bars=left,
                        right_bars=right,
                    )
                )
            if _is_pivot_low(candles, i, left, right):
                confirmed.append(
                    SwingPoint(
                        type=SwingType.LOW,
                        price=candles[i].low,
                        pivot_timestamp=candles[i].timestamp,
                        confirmed_at=confirmed_at,
                        left_bars=left,
                        right_bars=right,
                    )
                )
        else:
            if _looks_like_candidate_high(candles, i, left, available_right):
                candidates.append(
                    CandidatePivot(
                        type=SwingType.HIGH,
                        price=candles[i].high,
                        pivot_timestamp=candles[i].timestamp,
                        left_bars=left,
                        right_bars_required=right,
                        right_bars_available=available_right,
                    )
                )
            if _looks_like_candidate_low(candles, i, left, available_right):
                candidates.append(
                    CandidatePivot(
                        type=SwingType.LOW,
                        price=candles[i].low,
                        pivot_timestamp=candles[i].timestamp,
                        left_bars=left,
                        right_bars_required=right,
                        right_bars_available=available_right,
                    )
                )

    confirmed.sort(key=lambda s: (s.pivot_timestamp, s.type.value))
    candidates.sort(key=lambda c: (c.pivot_timestamp, c.type.value))
    return SwingDetectionResult(confirmed=confirmed, candidates=candidates)
