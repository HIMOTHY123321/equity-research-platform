"""Phase 12 (#G): the one and only place future data may enter this
package -- mirroring the exact "one place allowed to look at candles after
the fact" discipline app.research.outcomes already established (ADR 0008).
A ForwardForecast is never rewritten; this always produces a brand-new,
separate ForecastOutcome row linked by `forecast_id`.

Horizons are counted in bars by walking forward through real candles
(`forward_candles`, reused verbatim from app.research.outcomes), never by
calendar-time arithmetic -- this is what makes weekend/holiday/session
boundaries handle themselves correctly, the same way Phase 7 replay and
Phase 9 excursion analysis already do.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from app.ai_analysis.market_snapshot import build_market_snapshot
from app.ai_analysis.repository import EvidenceRepository
from app.forecasting.schemas import (
    CatalystReactionForecastValue,
    DirectionForecastValue,
    ForecastCategory,
    ForecastOutcome,
    ForecastOutcomeCategory,
    ForwardForecast,
    SetupOutcomeForecastValue,
    StructureForecastValue,
    VolatilityForecastValue,
)
from app.market_structure.common import candle_complete_at
from app.news.config import DEFAULT_CATALYST_CONFIG
from app.news.reaction import measure_market_reaction
from app.research.outcomes import evaluate_setup_outcome, forward_candles
from app.schemas.market_data import Timeframe
from app.support_resistance.schemas import LevelKind, Zone

if TYPE_CHECKING:
    from app.market_data.provider import MarketDataProvider
    from app.news.provider import NewsProvider
    from app.news.repository import NewsRepository

_DIRECTION_FLAT_BAND_MIN_PERCENT = 0.05
_DIRECTION_FLAT_BAND_ATR_FRACTION = 0.10
_VOLATILITY_EXPANSION_RATIO = 1.10
_VOLATILITY_CONTRACTION_RATIO = 0.90
_SETUP_FAVORABLE_ATR_THRESHOLD = 1.0
_SETUP_ADVERSE_ATR_THRESHOLD = 1.0


def _outcome_id(forecast_id: str, resolved_at: datetime) -> str:
    digest_source = f"{forecast_id}|{resolved_at.isoformat()}"
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]


def _insufficient(forecast: ForwardForecast, generated_at: datetime, detail: str) -> ForecastOutcome:
    return ForecastOutcome(
        outcome_id=_outcome_id(forecast.forecast_id, generated_at),
        forecast_id=forecast.forecast_id,
        resolved_at=generated_at,
        resolution_as_of=forecast.market_as_of,
        outcome=ForecastOutcomeCategory.INSUFFICIENT_FUTURE_DATA,
        detail=detail,
    )


def resolve_forecast(
    forecast: ForwardForecast,
    market_provider: "MarketDataProvider",
    evidence_repository: EvidenceRepository,
    news_provider: Optional["NewsProvider"] = None,
    news_repository: Optional["NewsRepository"] = None,
    *,
    now: Optional[datetime] = None,
) -> ForecastOutcome:
    resolved_at = now or datetime.now(timezone.utc)
    timeframe = Timeframe(forecast.timeframe)

    all_candles = market_provider.get_candles(forecast.symbol, timeframe, limit=50_000)
    future = forward_candles(all_candles, forecast.market_as_of)
    if len(future) < forecast.forecast_horizon_bars:
        return _insufficient(
            forecast,
            resolved_at,
            f"Only {len(future)} future candle(s) available; {forecast.forecast_horizon_bars} needed.",
        )

    horizon_candle = future[forecast.forecast_horizon_bars - 1]
    resolution_as_of = candle_complete_at(horizon_candle)
    base_candle = next((c for c in all_candles if c.timestamp == forecast.market_as_of), None)
    if base_candle is None:
        return _insufficient(forecast, resolved_at, "Base candle at market_as_of is no longer available.")

    if forecast.status.value == "abstained":
        return _insufficient(forecast, resolved_at, "Forecast abstained; nothing to resolve.")

    if forecast.forecast_category == ForecastCategory.DIRECTION:
        return _resolve_direction(forecast, resolved_at, resolution_as_of, base_candle, horizon_candle)
    if forecast.forecast_category == ForecastCategory.VOLATILITY:
        return _resolve_volatility(
            forecast, resolved_at, resolution_as_of, market_provider, evidence_repository
        )
    if forecast.forecast_category == ForecastCategory.STRUCTURE:
        return _resolve_structure(
            forecast, resolved_at, resolution_as_of, market_provider, evidence_repository
        )
    if forecast.forecast_category == ForecastCategory.SETUP_OUTCOME:
        return _resolve_setup_outcome(
            forecast, resolved_at, resolution_as_of, all_candles, evidence_repository
        )
    if forecast.forecast_category == ForecastCategory.CATALYST_REACTION:
        return _resolve_catalyst_reaction(
            forecast, resolved_at, resolution_as_of, all_candles, news_repository
        )
    return _insufficient(forecast, resolved_at, f"No resolver for {forecast.forecast_category.value}.")


def _classify_direction(return_percent: float, atr_percent: Optional[float]) -> str:
    band = max(
        _DIRECTION_FLAT_BAND_MIN_PERCENT, _DIRECTION_FLAT_BAND_ATR_FRACTION * (atr_percent or 0.0)
    )
    if abs(return_percent) <= band:
        return DirectionForecastValue.FLAT.value
    return DirectionForecastValue.UP.value if return_percent > 0 else DirectionForecastValue.DOWN.value


def _resolve_direction(
    forecast, resolved_at, resolution_as_of, base_candle, horizon_candle
) -> ForecastOutcome:
    return_percent = (horizon_candle.close - base_candle.close) / base_candle.close * 100
    atr_percent = None  # a band without ATR context still uses the min-percent floor
    actual = _classify_direction(return_percent, atr_percent)

    if actual == forecast.forecast_value:
        outcome = ForecastOutcomeCategory.CORRECT
    elif DirectionForecastValue.FLAT.value in (forecast.forecast_value, actual):
        outcome = ForecastOutcomeCategory.NEUTRAL_UNRESOLVED
    else:
        outcome = ForecastOutcomeCategory.INCORRECT

    return ForecastOutcome(
        outcome_id=_outcome_id(forecast.forecast_id, resolved_at),
        forecast_id=forecast.forecast_id,
        resolved_at=resolved_at,
        resolution_as_of=resolution_as_of,
        outcome=outcome,
        actual_value=actual,
        actual_forward_return_percent=return_percent,
        market_data_cutoff=horizon_candle.timestamp,
        detail=f"Actual close-to-close return {return_percent:.3f}% classified as {actual}.",
    )


def _resolve_volatility(
    forecast, resolved_at, resolution_as_of, market_provider, evidence_repository
) -> ForecastOutcome:
    packet = evidence_repository.get_packet(forecast.evidence_packet_id)
    creation_atr = packet.features.atr.value if packet is not None and packet.features.atr else None
    if creation_atr is None:
        return _insufficient(forecast, resolved_at, "Creation-time ATR unavailable.")

    snapshot = build_market_snapshot(
        forecast.symbol, Timeframe(forecast.timeframe), market_provider, resolution_as_of
    )
    horizon_atr = snapshot.feature_snapshot.atr.value if snapshot.feature_snapshot.atr else None
    if horizon_atr is None:
        return _insufficient(forecast, resolved_at, "Horizon-time ATR unavailable.")

    ratio = horizon_atr / creation_atr if creation_atr else None
    actual = None
    if ratio is None:
        outcome = ForecastOutcomeCategory.INSUFFICIENT_FUTURE_DATA
    elif ratio >= _VOLATILITY_EXPANSION_RATIO:
        actual = VolatilityForecastValue.EXPANDS.value
        outcome = (
            ForecastOutcomeCategory.CORRECT
            if forecast.forecast_value == actual
            else ForecastOutcomeCategory.INCORRECT
        )
    elif ratio <= _VOLATILITY_CONTRACTION_RATIO:
        actual = VolatilityForecastValue.CONTRACTS.value
        outcome = (
            ForecastOutcomeCategory.CORRECT
            if forecast.forecast_value == actual
            else ForecastOutcomeCategory.INCORRECT
        )
    else:
        outcome = ForecastOutcomeCategory.NEUTRAL_UNRESOLVED

    return ForecastOutcome(
        outcome_id=_outcome_id(forecast.forecast_id, resolved_at),
        forecast_id=forecast.forecast_id,
        resolved_at=resolved_at,
        resolution_as_of=resolution_as_of,
        outcome=outcome,
        actual_value=actual,
        market_data_cutoff=snapshot.market_data_cutoff,
        detail=(
            f"ATR ratio (horizon/creation) = {ratio:.3f}" if ratio is not None else "ATR ratio unavailable"
        ),
    )


def _find_zone_by_id(levels_snapshot, zone_ref: Optional[str]) -> Optional[Zone]:
    for pool in (
        levels_snapshot.active_support_zones,
        levels_snapshot.active_resistance_zones,
        levels_snapshot.recent_broken_zones,
    ):
        for zone in pool:
            if zone.id == zone_ref:
                return zone
    return None


def _find_overlapping_zone(
    levels_snapshot, kind: LevelKind, lower_bound: float, upper_bound: float
) -> Optional[Zone]:
    """Zone IDs are a pure function of cluster *membership*
    (app.support_resistance.ids.zone_id), which routinely shifts as new
    candles arrive and levels re-cluster -- the exact same zone_ref is
    essentially never still present at a later `as_of`, even one bar later.
    Re-identify "the same structural level" by price-range overlap instead,
    scoped to the original zone's own kind (support stays support,
    resistance stays resistance) and restricted to zones already known to
    have been active or recently broken by the resolution instant."""
    candidates = list(
        levels_snapshot.active_support_zones
        if kind == LevelKind.SUPPORT
        else levels_snapshot.active_resistance_zones
    )
    candidates += [z for z in levels_snapshot.recent_broken_zones if z.kind == kind]
    for zone in candidates:
        if zone.lower_bound <= upper_bound and zone.upper_bound >= lower_bound:
            return zone
    return None


def _resolve_structure(
    forecast, resolved_at, resolution_as_of, market_provider, evidence_repository
) -> ForecastOutcome:
    snapshot = build_market_snapshot(
        forecast.symbol, Timeframe(forecast.timeframe), market_provider, resolution_as_of
    )
    levels = snapshot.levels_snapshot
    structure = snapshot.structure_by_timeframe.get(Timeframe(forecast.timeframe))

    if forecast.forecast_value in (
        StructureForecastValue.RESISTANCE_BREAKS.value,
        StructureForecastValue.RESISTANCE_REJECTS.value,
        StructureForecastValue.SUPPORT_HOLDS.value,
        StructureForecastValue.SUPPORT_FAILS.value,
    ):
        original_packet = evidence_repository.get_packet(forecast.evidence_packet_id)
        original_zone = (
            _find_zone_by_id(original_packet.support_resistance, forecast.zone_ref)
            if original_packet is not None
            else None
        )
        if original_zone is None:
            return _insufficient(
                forecast, resolved_at, "Referenced zone not found on the original evidence packet."
            )
        zone = _find_overlapping_zone(
            levels, original_zone.kind, original_zone.lower_bound, original_zone.upper_bound
        )
        if zone is None:
            return _insufficient(forecast, resolved_at, "Referenced zone no longer resolvable.")
        broken_within_horizon = (
            zone.break_event is not None
            and forecast.market_as_of < zone.break_event.first_broken_at <= resolution_as_of
        )
        is_resistance_side = forecast.forecast_value in (
            StructureForecastValue.RESISTANCE_BREAKS.value,
            StructureForecastValue.RESISTANCE_REJECTS.value,
        )
        if is_resistance_side:
            actual = (
                StructureForecastValue.RESISTANCE_BREAKS.value
                if broken_within_horizon
                else StructureForecastValue.RESISTANCE_REJECTS.value
            )
        else:
            actual = (
                StructureForecastValue.SUPPORT_FAILS.value
                if broken_within_horizon
                else StructureForecastValue.SUPPORT_HOLDS.value
            )
        outcome = (
            ForecastOutcomeCategory.CORRECT
            if actual == forecast.forecast_value
            else ForecastOutcomeCategory.INCORRECT
        )
        broken_or_held = "broken" if broken_within_horizon else "held"
        detail = f"Zone {forecast.zone_ref} was {broken_or_held} within the forecast horizon."
    elif forecast.forecast_value in (
        StructureForecastValue.BOS_OCCURS.value,
        StructureForecastValue.CHOCH_OCCURS.value,
    ):
        events = (
            structure.breaks_of_structure
            if forecast.forecast_value == StructureForecastValue.BOS_OCCURS.value
            else structure.changes_of_character
        )
        occurred = any(forecast.market_as_of < e.break_timestamp <= resolution_as_of for e in events)
        actual = forecast.forecast_value if occurred else "no_event"
        outcome = ForecastOutcomeCategory.CORRECT if occurred else ForecastOutcomeCategory.INCORRECT
        detail = f"{'An' if occurred else 'No'} event occurred within the forecast horizon."
    else:  # RANGE_PERSISTS / RANGE_RESOLVES
        active_range = structure.active_range
        persists = active_range.status.value == "ok"
        actual = (
            StructureForecastValue.RANGE_PERSISTS.value
            if persists
            else StructureForecastValue.RANGE_RESOLVES.value
        )
        outcome = (
            ForecastOutcomeCategory.CORRECT
            if actual == forecast.forecast_value
            else ForecastOutcomeCategory.INCORRECT
        )
        detail = f"Active range {'persisted' if persists else 'resolved'} through the forecast horizon."

    return ForecastOutcome(
        outcome_id=_outcome_id(forecast.forecast_id, resolved_at),
        forecast_id=forecast.forecast_id,
        resolved_at=resolved_at,
        resolution_as_of=resolution_as_of,
        outcome=outcome,
        actual_value=actual,
        market_data_cutoff=snapshot.market_data_cutoff,
        detail=detail,
    )


def _resolve_setup_outcome(
    forecast, resolved_at, resolution_as_of, all_candles, evidence_repository
) -> ForecastOutcome:
    packet = evidence_repository.get_packet(forecast.evidence_packet_id)
    if packet is None or packet.setup is None:
        return _insufficient(forecast, resolved_at, "Original setup candidate is no longer available.")

    setup_outcome = evaluate_setup_outcome(packet.setup.candidate, all_candles)
    if setup_outcome is None or not setup_outcome.evaluation_quality.fully_evaluated:
        return _insufficient(forecast, resolved_at, "Setup outcome could not be fully evaluated yet.")

    mfe_atr = setup_outcome.mfe.atr
    mae_atr = setup_outcome.mae.atr
    mfe_hit = mfe_atr is not None and mfe_atr >= _SETUP_FAVORABLE_ATR_THRESHOLD
    mae_hit = mae_atr is not None and mae_atr <= -_SETUP_ADVERSE_ATR_THRESHOLD
    invalidated = packet.setup.candidate.current_state.value in ("invalidated", "rejected", "expired")

    favorable_first = mfe_hit and (
        not mae_hit or (setup_outcome.mfe.bars_until or 0) <= (setup_outcome.mae.bars_until or 10**9)
    )
    if invalidated:
        actual = SetupOutcomeForecastValue.INVALIDATES_BEFORE_CONFIRMATION.value
        resolvable = True
    elif favorable_first:
        actual = SetupOutcomeForecastValue.FAVORABLE_BEFORE_ADVERSE.value
        resolvable = True
    elif mae_hit:
        actual = "adverse_before_favorable"
        resolvable = True
    else:
        actual = SetupOutcomeForecastValue.REMAINS_UNRESOLVED.value
        resolvable = False

    if not resolvable:
        outcome = (
            ForecastOutcomeCategory.CORRECT
            if forecast.forecast_value == SetupOutcomeForecastValue.REMAINS_UNRESOLVED.value
            else ForecastOutcomeCategory.NEUTRAL_UNRESOLVED
        )
    else:
        outcome = (
            ForecastOutcomeCategory.CORRECT
            if actual == forecast.forecast_value
            else ForecastOutcomeCategory.INCORRECT
        )

    return ForecastOutcome(
        outcome_id=_outcome_id(forecast.forecast_id, resolved_at),
        forecast_id=forecast.forecast_id,
        resolved_at=resolved_at,
        resolution_as_of=resolution_as_of,
        outcome=outcome,
        actual_value=actual,
        actual_mfe_atr=mfe_atr,
        actual_mae_atr=mae_atr,
        market_data_cutoff=setup_outcome.evaluation_end,
        detail=f"MFE {mfe_atr} ATR / MAE {mae_atr} ATR over the evaluation window.",
    )


def _resolve_catalyst_reaction(
    forecast, resolved_at, resolution_as_of, all_candles, news_repository
) -> ForecastOutcome:
    if news_repository is None:
        return _insufficient(
            forecast, resolved_at, "No news repository available to re-measure the reaction."
        )
    event_ref = next((r for r in forecast.evidence_refs if r.startswith("catalyst:")), None)
    if event_ref is None:
        return _insufficient(forecast, resolved_at, "No catalyst event reference on this forecast.")
    event_id = event_ref.split(":", 1)[1]
    event = news_repository.get_event_by_id(event_id)
    if event is None:
        return _insufficient(forecast, resolved_at, "Catalyst event no longer resolvable.")

    reaction = measure_market_reaction(
        event, forecast.symbol, forecast.timeframe, all_candles, DEFAULT_CATALYST_CONFIG
    )
    available = sorted((h for h in reaction.price_horizons if h.available), key=lambda h: h.horizon_bars)
    if len(available) < 2:
        return _insufficient(forecast, resolved_at, "Not enough reaction horizons available to resolve yet.")

    first, last = available[0], available[-1]
    ratio = (
        (last.directional_return_percent / first.directional_return_percent)
        if first.directional_return_percent not in (None, 0)
        else None
    )
    actual = None
    if ratio is None:
        outcome = ForecastOutcomeCategory.INSUFFICIENT_FUTURE_DATA
    elif ratio >= DEFAULT_CATALYST_CONFIG.reaction_persist_threshold_ratio:
        actual = CatalystReactionForecastValue.PERSISTS.value
        outcome = (
            ForecastOutcomeCategory.CORRECT
            if forecast.forecast_value == actual
            else ForecastOutcomeCategory.INCORRECT
        )
    elif ratio <= DEFAULT_CATALYST_CONFIG.reaction_fade_threshold_ratio:
        actual = CatalystReactionForecastValue.FADES.value
        outcome = (
            ForecastOutcomeCategory.CORRECT
            if forecast.forecast_value == actual
            else ForecastOutcomeCategory.INCORRECT
        )
    else:
        outcome = ForecastOutcomeCategory.NEUTRAL_UNRESOLVED

    return ForecastOutcome(
        outcome_id=_outcome_id(forecast.forecast_id, resolved_at),
        forecast_id=forecast.forecast_id,
        resolved_at=resolved_at,
        resolution_as_of=resolution_as_of,
        outcome=outcome,
        actual_value=actual,
        market_data_cutoff=reaction.computed_at,
        detail=f"Reaction persistence ratio = {ratio}" if ratio is not None else "Reaction ratio unavailable",
    )
