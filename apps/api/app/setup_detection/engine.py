"""The single entry point: (candles, FeatureSnapshot, MarketStructureSnapshot
per timeframe, SupportResistanceSnapshot) -> SetupDetectionSnapshot.

Same as-of/no-lookahead discipline as Phases 3-5: candles are defensively
re-truncated to `as_of` and reduced to completed-only bars here, independent
of caller correctness (see app.market_structure.common, reused directly --
this package is explicitly built as a consumer of Phases 3-5's already
lookahead-safe outputs, so it follows Phase 5's precedent of depending on
Phase 4's common module rather than re-duplicating it a third time; see the
ADR).

Each detector is a pure function; this module only orchestrates them,
applies expiration (#25), and buckets/bounds the result for the API (#29).
"""

from __future__ import annotations

from datetime import datetime

from app.features.schemas import FeatureSnapshot
from app.market_structure.common import completed_only, truncate_to_as_of
from app.market_structure.schemas import MarketStructureSnapshot
from app.schemas.market_data import Candle, Timeframe
from app.setup_detection.config import DEFAULT_SETUP_DETECTION_CONFIG, SetupDetectionConfig
from app.setup_detection.context import DetectorInputs
from app.setup_detection.detectors import (
    breakout_retest,
    failed_breakout,
    gap_continuation,
    gap_fill,
    liquidity_sweep,
    moving_average_reclaim,
    previous_day_breakout,
    previous_week_breakout,
    range_breakout,
    resistance_rejection,
    support_reclaim,
    trend_pullback,
)
from app.setup_detection.lifecycle import is_past_expiration, transition
from app.setup_detection.schemas import (
    SetupCandidate,
    SetupDetectionDataQuality,
    SetupDetectionSnapshot,
    SetupDetectionStatus,
    SetupLifecycleState,
)
from app.support_resistance.schemas import SupportResistanceSnapshot

_DETECTORS = (
    ("previous_day_breakout", previous_day_breakout.detect),
    ("previous_week_breakout", previous_week_breakout.detect),
    ("breakout_retest", breakout_retest.detect),
    ("failed_breakout", failed_breakout.detect),
    ("support_reclaim", support_reclaim.detect),
    ("resistance_rejection", resistance_rejection.detect),
    ("gap_continuation", gap_continuation.detect),
    ("gap_fill", gap_fill.detect),
    ("liquidity_sweep", liquidity_sweep.detect),
    ("moving_average_reclaim", moving_average_reclaim.detect),
    ("trend_pullback", trend_pullback.detect),
    ("range_breakout", range_breakout.detect),
)


def compute_setup_detection_snapshot(
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
    daily_candles: list[Candle],
    feature_snapshot: FeatureSnapshot,
    structure_by_timeframe: dict[Timeframe, MarketStructureSnapshot],
    levels_snapshot: SupportResistanceSnapshot,
    as_of: datetime,
    config: SetupDetectionConfig = DEFAULT_SETUP_DETECTION_CONFIG,
) -> SetupDetectionSnapshot:
    truncated, future_dropped = truncate_to_as_of(candles, as_of)
    completed = completed_only(truncated, as_of)
    daily_truncated, _ = truncate_to_as_of(daily_candles, as_of)
    daily_completed = completed_only(daily_truncated, as_of)

    warnings: list[str] = []
    if future_dropped:
        warnings.append(f"Dropped {future_dropped} candle(s) timestamped after as_of")

    # Data-quality gate (#22): don't run detectors, and don't pretend
    # favorable conditions, when there isn't enough history to evaluate
    # against honestly.
    if len(completed) < config.min_candles_required:
        warnings.append(
            f"Only {len(completed)} completed candle(s) available; {config.min_candles_required} required"
        )
        return SetupDetectionSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            as_of=as_of,
            qualified_setups=[],
            candidates=[],
            rejected_candidates=[],
            recently_invalidated=[],
            recently_expired=[],
            data_quality=SetupDetectionDataQuality(
                status=SetupDetectionStatus.UNAVAILABLE,
                source_timeframe=timeframe,
                candles_consumed=len(completed),
                detectors_run=0,
                detectors_skipped=[name for name, _ in _DETECTORS],
                warnings=warnings,
            ),
        )

    inputs = DetectorInputs(
        symbol=symbol,
        timeframe=timeframe,
        candles=completed,
        daily_candles=daily_completed,
        as_of=as_of,
        feature_snapshot=feature_snapshot,
        structure_by_timeframe=structure_by_timeframe,
        levels_snapshot=levels_snapshot,
        config=config,
    )

    all_candidates: list[SetupCandidate] = []
    detectors_run = 0
    for _name, detect_fn in _DETECTORS:
        all_candidates.extend(detect_fn(inputs))
        detectors_run += 1

    resolved = [_apply_expiration(candidate, as_of, config) for candidate in all_candidates]

    qualified = _sorted_recent(
        [
            c
            for c in resolved
            if c.current_state in (SetupLifecycleState.QUALIFIED, SetupLifecycleState.TRIGGERED)
        ]
    )[: config.max_qualified_in_snapshot]
    pending = _sorted_recent([c for c in resolved if c.current_state == SetupLifecycleState.CANDIDATE])[
        : config.max_candidates_in_snapshot
    ]
    rejected = _sorted_recent([c for c in resolved if c.current_state == SetupLifecycleState.REJECTED])[
        : config.max_rejected_in_snapshot
    ]
    invalidated = _sorted_recent([c for c in resolved if c.current_state == SetupLifecycleState.INVALIDATED])[
        : config.max_recently_invalidated_in_snapshot
    ]
    expired = _sorted_recent([c for c in resolved if c.current_state == SetupLifecycleState.EXPIRED])[
        : config.max_recently_expired_in_snapshot
    ]

    return SetupDetectionSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        as_of=as_of,
        qualified_setups=qualified,
        candidates=pending,
        rejected_candidates=rejected,
        recently_invalidated=invalidated,
        recently_expired=expired,
        data_quality=SetupDetectionDataQuality(
            status=SetupDetectionStatus.OK,
            source_timeframe=timeframe,
            candles_consumed=len(completed),
            detectors_run=detectors_run,
            warnings=warnings,
        ),
    )


def _apply_expiration(
    candidate: SetupCandidate, as_of: datetime, config: SetupDetectionConfig
) -> SetupCandidate:
    """Re-derived fresh from `expires_at`/`as_of` on every call, same
    non-mutated-state pattern as Phase 4's apply_break_state -- a
    candidate's terminal states (REJECTED, INVALIDATED, TRIGGERED) never
    expire; only a still-live CANDIDATE/QUALIFIED can."""
    if candidate.current_state not in (SetupLifecycleState.CANDIDATE, SetupLifecycleState.QUALIFIED):
        return candidate
    if not is_past_expiration(candidate.expires_at, as_of):
        return candidate

    expiry_transition = transition(
        SetupLifecycleState.EXPIRED,
        candidate.expires_at,
        "candidate_expired",
        "No confirmation within the configured window",
    )
    return candidate.model_copy(
        update={
            "current_state": SetupLifecycleState.EXPIRED,
            "transitions": [*candidate.transitions, expiry_transition],
            "expired_at": candidate.expires_at,
        }
    )


def _sorted_recent(candidates: list[SetupCandidate]) -> list[SetupCandidate]:
    return sorted(candidates, key=lambda c: c.candidate_candle_timestamp, reverse=True)
