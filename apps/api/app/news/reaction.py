"""Market reaction measurement (#F). Reuses existing deterministic engines
rather than reimplementing them:

- Price horizons/excursion: `app.research.outcomes.compute_horizon_outcomes`
  / `compute_excursion` / `forward_candles`, verbatim.
- RVOL: `app.features.volume.average_volume`, verbatim.
- Session classification: `app.market_data.sessions`, plus a genuine
  weekend/non-trading check on top (a catalyst, unlike a candle, can be
  published at any wall-clock moment, including a non-trading day).

Reaction is measured in a neutral, non-directional convention (always
`Direction.BULLISH` is passed to the reused outcome functions, so
`directional_return_percent == raw_return_percent`, and MFE/MAE are plain
"highest high move" / "lowest low move" -- never relative to any setup's own
direction). Reinterpreting a reaction relative to a specific setup's
direction is `app.news.setup_linking`'s job, done strictly after this
module has already produced a direction-neutral measurement.

Structure fields (nearest S/R, BOS/CHOCH after the event) are attached by
the caller from already-computed Phase 4/5 snapshots at the event's own
timestamp -- this module never recomputes market structure or
support/resistance itself; see `attach_structure_context`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.features.volume import average_volume
from app.market_data.sessions import EXCHANGE_TZ, classify_timestamp_session
from app.market_structure.schemas import Direction, MarketStructureSnapshot
from app.news.config import DEFAULT_CATALYST_CONFIG, CatalystConfig
from app.news.schemas import CatalystEvent, MarketReaction, ReactionSession
from app.research.outcomes import compute_excursion, compute_horizon_outcomes, forward_candles
from app.research.schemas import EvaluationQuality
from app.schemas.market_data import Candle
from app.support_resistance.schemas import SupportResistanceSnapshot

_RVOL_LOOKBACK_BARS = 20


def classify_reaction_session(timestamp: datetime) -> ReactionSession:
    local = timestamp.astimezone(EXCHANGE_TZ)
    if local.weekday() >= 5:  # Saturday=5, Sunday=6
        return ReactionSession.WEEKEND_NON_TRADING
    return ReactionSession(classify_timestamp_session(timestamp).value)


def _base_candle_index(candles: list[Candle], at: datetime) -> Optional[int]:
    """The last candle at or before `at` -- the best known price context
    right before the catalyst. `None` if every candle is after `at` (the
    event predates the available candle history)."""
    index = None
    for i, candle in enumerate(candles):
        if candle.timestamp <= at:
            index = i
        else:
            break
    return index


def measure_market_reaction(
    event: CatalystEvent,
    symbol: str,
    timeframe: str,
    candles: list[Candle],
    config: CatalystConfig = DEFAULT_CATALYST_CONFIG,
    computed_at: Optional[datetime] = None,
) -> MarketReaction:
    """Candles must already be truncated by the caller to whatever `as_of`
    is in effect (same discipline every other engine in this codebase
    follows) -- this function itself never fetches or looks past what it is
    given."""
    session = classify_reaction_session(event.primary_timestamp)
    computed_at = computed_at or datetime.now(timezone.utc)

    base_index = _base_candle_index(candles, event.primary_timestamp)
    if base_index is None:
        return MarketReaction(
            event_id=event.event_id,
            symbol=symbol,
            timeframe=timeframe,
            session_at_event=session,
            evaluation_quality=EvaluationQuality(
                bars_available_after_detection=0,
                fully_evaluated=False,
                warnings=["No candle history available at or before the event timestamp"],
            ),
            computed_at=computed_at,
        )

    base_candle = candles[base_index]
    base_price = base_candle.close
    future_candles = forward_candles(candles, base_candle.timestamp)

    horizons = compute_horizon_outcomes(
        future_candles, base_price, Direction.BULLISH, config.reaction_horizons_bars
    )
    mfe = compute_excursion(future_candles, base_price, Direction.BULLISH, atr=None, favorable=True)
    mae = compute_excursion(future_candles, base_price, Direction.BULLISH, atr=None, favorable=False)

    rvol = None
    volume_spike_ratio = None
    baseline_volume = average_volume(candles[: base_index + 1], _RVOL_LOOKBACK_BARS)
    if baseline_volume:
        rvol = base_candle.volume / baseline_volume
        volume_spike_ratio = rvol

    max_horizon = max(config.reaction_horizons_bars)
    fully_evaluated = len(future_candles) >= max_horizon
    warnings = []
    if not fully_evaluated:
        warnings.append(
            f"Only {len(future_candles)} future candle(s) available; "
            f"{max_horizon} needed for the longest horizon"
        )

    return MarketReaction(
        event_id=event.event_id,
        symbol=symbol,
        timeframe=timeframe,
        session_at_event=session,
        base_price=base_price,
        price_horizons=horizons,
        mfe=mfe,
        mae=mae,
        rvol_at_event=rvol,
        volume_spike_ratio=volume_spike_ratio,
        evaluation_quality=EvaluationQuality(
            bars_available_after_detection=len(future_candles),
            fully_evaluated=fully_evaluated,
            warnings=warnings,
        ),
        computed_at=computed_at,
    )


def attach_structure_context(
    reaction: MarketReaction,
    structure_snapshot: Optional[MarketStructureSnapshot],
    levels_snapshot: Optional[SupportResistanceSnapshot],
    event_timestamp: datetime,
) -> MarketReaction:
    """Read-only decoration pass (#F), strictly after `measure_market_reaction`
    -- never recomputes price/volume, only attaches already-computed Phase
    4/5 structure at the event's own timestamp. `structure_snapshot`/
    `levels_snapshot` must already be computed with `as_of` at or after the
    event so their BOS/CHOCH/zone data is meaningful for "after this event";
    the caller owns that discipline (same as every other cross-engine
    consumer in this codebase)."""
    updates: dict = {}

    if levels_snapshot is not None:
        if levels_snapshot.nearest_support is not None:
            updates["nearest_support_price"] = levels_snapshot.nearest_support.representative_price
        if levels_snapshot.nearest_resistance is not None:
            updates["nearest_resistance_price"] = levels_snapshot.nearest_resistance.representative_price

    if structure_snapshot is not None:
        updates["structure_state_at_event"] = structure_snapshot.trend.trend.value
        updates["bos_after_event"] = any(
            b.break_timestamp >= event_timestamp for b in structure_snapshot.breaks_of_structure
        )
        updates["choch_after_event"] = any(
            c.break_timestamp >= event_timestamp for c in structure_snapshot.changes_of_character
        )

    return reaction.model_copy(update=updates) if updates else reaction
