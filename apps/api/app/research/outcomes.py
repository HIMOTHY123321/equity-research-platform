"""Outcome evaluation (#9-#17). This module is the one and only place in
the codebase allowed to look at candles after a setup's own detection
instant -- see docs/decisions/0008 for the detection/evaluation boundary
this enforces. Nothing here is a trading target: no entries, no stops, no
profit targets, no win/loss labels (#53).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.market_structure.schemas import Direction
from app.research.config import DEFAULT_RESEARCH_CONFIG, ResearchConfig
from app.research.schemas import (
    EvaluationQuality,
    ExcursionMetrics,
    HorizonOutcome,
    SetupOutcome,
    StructuralEventOutcome,
)
from app.schemas.market_data import Candle
from app.setup_detection.schemas import SetupCandidate


def directional_delta(price: float, base_price: float, direction: Direction) -> float:
    """Positive = favorable movement, negative = adverse -- same convention
    `directional_return_percent` already uses (#10)."""
    return (price - base_price) if direction == Direction.BULLISH else (base_price - price)


def forward_candles(candles: list[Candle], after: datetime) -> list[Candle]:
    future = [c for c in candles if c.timestamp > after]
    future.sort(key=lambda c: c.timestamp)
    return future


def compute_horizon_outcomes(
    future_candles: list[Candle], base_price: float, direction: Direction, horizons: tuple
) -> list[HorizonOutcome]:
    results = []
    for horizon_bars in horizons:
        if len(future_candles) < horizon_bars:
            results.append(HorizonOutcome(horizon_bars=horizon_bars, available=False))
            continue
        target = future_candles[horizon_bars - 1]
        absolute_change = target.close - base_price
        raw_return_percent = absolute_change / base_price * 100
        directional_return_percent = (
            raw_return_percent if direction == Direction.BULLISH else -raw_return_percent
        )
        results.append(
            HorizonOutcome(
                horizon_bars=horizon_bars,
                available=True,
                future_close=target.close,
                absolute_change=absolute_change,
                raw_return_percent=raw_return_percent,
                directional_return_percent=directional_return_percent,
            )
        )
    return results


def compute_excursion(
    future_candles: list[Candle],
    base_price: float,
    direction: Direction,
    atr: Optional[float],
    favorable: bool,
) -> ExcursionMetrics:
    """MFE (#11) when `favorable=True`, MAE (#12) when `favorable=False`.
    Favorable movement is read from the high for a bullish setup / the low
    for a bearish one (the best price could have offered); adverse movement
    is read from the opposite extreme -- never the close, since a setup can
    travel far beyond its eventual closing price in either direction (#13).
    """
    if not future_candles:
        return ExcursionMetrics()

    use_high = (direction == Direction.BULLISH) == favorable
    best_index = None
    best_delta = None
    for idx, candle in enumerate(future_candles):
        price = candle.high if use_high else candle.low
        delta = directional_delta(price, base_price, direction)
        if best_delta is None:
            best_index, best_delta = idx, delta
            continue
        if favorable and delta > best_delta:
            best_index, best_delta = idx, delta
        if not favorable and delta < best_delta:
            best_index, best_delta = idx, delta

    return ExcursionMetrics(
        absolute=best_delta,
        percent=(best_delta / base_price * 100) if base_price else None,
        atr=(best_delta / atr) if atr else None,
        bars_until=best_index + 1,
        timestamp=future_candles[best_index].timestamp,
    )


def compute_structural_events(
    candidate: SetupCandidate,
    future_candles: list[Candle],
    config: ResearchConfig,
) -> list[StructuralEventOutcome]:
    """Deliberately small, objective initial set (#15) -- both derived
    purely from fields already on the frozen detection context/candidate,
    never a fabricated trading target."""
    events: list[StructuralEventOutcome] = []

    if candidate.reference_price is not None:
        tolerance = candidate.reference_price * (config.retest_tolerance_percent / 100)
        retest = next(
            (
                (idx, c)
                for idx, c in enumerate(future_candles)
                if c.low - tolerance <= candidate.reference_price <= c.high + tolerance
            ),
            None,
        )
        events.append(
            StructuralEventOutcome(
                code="reference_level_retested",
                occurred=retest is not None,
                timestamp=retest[1].timestamp if retest else None,
                bars_until=(retest[0] + 1) if retest else None,
            )
        )

    context = candidate.context
    if context is not None and context.active_range_high is not None and context.active_range_low is not None:
        opposite_bound = (
            context.active_range_low
            if candidate.direction == Direction.BULLISH
            else context.active_range_high
        )
        reached = next(
            (
                (idx, c)
                for idx, c in enumerate(future_candles)
                if (
                    c.low <= opposite_bound
                    if candidate.direction == Direction.BULLISH
                    else c.high >= opposite_bound
                )
            ),
            None,
        )
        events.append(
            StructuralEventOutcome(
                code="active_range_opposite_boundary_reached",
                occurred=reached is not None,
                timestamp=reached[1].timestamp if reached else None,
                bars_until=(reached[0] + 1) if reached else None,
            )
        )

    return events


def evaluate_setup_outcome(
    candidate: SetupCandidate,
    all_candles: list[Candle],
    config: ResearchConfig = DEFAULT_RESEARCH_CONFIG,
) -> Optional[SetupOutcome]:
    """The single entry point: SetupCandidate + full candle series ->
    SetupOutcome. `all_candles` may (must) contain candles after
    `candidate.candidate_candle_timestamp` -- that is the entire point of
    this module -- but this function never looks at anything about the
    candidate other than its already-frozen detection-time fields."""
    detection_candle = next(
        (c for c in all_candles if c.timestamp == candidate.candidate_candle_timestamp), None
    )
    if detection_candle is None:
        return None

    base_price = detection_candle.close
    atr = candidate.context.atr if candidate.context else None
    future_candles = forward_candles(all_candles, candidate.candidate_candle_timestamp)

    horizons = compute_horizon_outcomes(
        future_candles, base_price, candidate.direction, config.forward_horizons
    )
    mfe = compute_excursion(future_candles, base_price, candidate.direction, atr, favorable=True)
    mae = compute_excursion(future_candles, base_price, candidate.direction, atr, favorable=False)
    structural_events = compute_structural_events(candidate, future_candles, config)

    warnings = []
    max_horizon = max(config.forward_horizons)
    fully_evaluated = len(future_candles) >= max_horizon
    if not fully_evaluated:
        warnings.append(
            f"Only {len(future_candles)} future candle(s) available; "
            f"{max_horizon} needed for the longest horizon"
        )

    return SetupOutcome(
        setup_id=candidate.id,
        base_price=base_price,
        detection_atr=atr,
        evaluation_start=candidate.candidate_candle_timestamp,
        evaluation_end=future_candles[-1].timestamp if future_candles else None,
        horizons=horizons,
        mfe=mfe,
        mae=mae,
        structural_events=structural_events,
        evaluation_quality=EvaluationQuality(
            bars_available_after_detection=len(future_candles),
            fully_evaluated=fully_evaluated,
            warnings=warnings,
        ),
    )
