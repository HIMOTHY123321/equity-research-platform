"""Moving-average reclaim (#15): the previous completed candle closed on
one side of a moving average, the current completed candle closes on the
other. Each MA (EMA20, SMA50, SMA200) is evaluated and labeled separately
via `metadata["moving_average"]` -- never combined into one vague check,
per the Phase 6 instructions.

Point-in-time MA values reuse the same `ema`/`sma` functions the feature
engine calls (see context.py) rather than duplicating the math.
"""

from __future__ import annotations

from app.market_structure.schemas import Direction, Timeframe
from app.setup_detection.conflicts import conflict_if_higher_timeframe_opposed
from app.setup_detection.context import DetectorInputs, point_in_time_ema, point_in_time_sma
from app.setup_detection.detectors._common import build_resolved_candidate
from app.setup_detection.evidence import check_rvol, check_trend_alignment
from app.setup_detection.schemas import EvidenceCheck, RuleType, SetupCandidate, SetupType

_MAS = (("ema20", "ema", 20), ("sma50", "sma", 50), ("sma200", "sma", 200))


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    if len(inputs.candles) < 210:
        return []

    candidates: list[SetupCandidate] = []
    daily_structure = inputs.structure_by_timeframe.get(Timeframe.ONE_DAY)

    # Bounded to the lookback window (#40) -- point-in-time MA recomputation
    # is O(bars examined) per call, so scanning the full multi-thousand-bar
    # history here (rather than just the window new candidates can come
    # from) would be pathological for 5m/15m timeframes.
    start_idx = max(1, len(inputs.candles) - inputs.config.detection_lookback_bars)

    for ma_key, ma_kind, period in _MAS:
        for idx in range(start_idx, len(inputs.candles)):
            candle = inputs.candles[idx]

            previous_ma = (
                point_in_time_ema(inputs.candles, period, idx - 1)
                if ma_kind == "ema"
                else point_in_time_sma(inputs.candles, period, idx - 1)
            )
            current_ma = (
                point_in_time_ema(inputs.candles, period, idx)
                if ma_kind == "ema"
                else point_in_time_sma(inputs.candles, period, idx)
            )
            if previous_ma is None or current_ma is None:
                continue

            previous_close = inputs.candles[idx - 1].close
            for direction in (Direction.BULLISH, Direction.BEARISH):
                candidate = _check_reclaim(
                    inputs,
                    candle,
                    previous_close,
                    previous_ma,
                    current_ma,
                    ma_key,
                    period,
                    direction,
                    daily_structure,
                )
                if candidate is not None:
                    candidates.append(candidate)

    return candidates


def _check_reclaim(
    inputs, candle, previous_close, previous_ma, current_ma, ma_key, period, direction, daily_structure
):
    if direction == Direction.BULLISH:
        was_below = previous_close < previous_ma
        now_above = candle.close > current_ma
        triggered = was_below and now_above
    else:
        was_below = previous_close > previous_ma
        now_above = candle.close < current_ma
        triggered = was_below and now_above
    if not triggered:
        return None

    label_dir = "above" if direction == Direction.BULLISH else "below"
    hard_check = EvidenceCheck(
        code="ma_reclaim_confirmed",
        label=f"Close {label_dir} {ma_key.upper()} after being on the opposite side",
        rule_type=RuleType.HARD,
        passed=True,
        actual=candle.close,
        required=current_ma,
        source=f"features.moving_averages.{ma_key}",
    )
    soft_checks = [
        check_rvol(inputs.feature_snapshot.volume.relative_volume, inputs.config.min_rvol_for_confirmation),
        check_trend_alignment(
            daily_structure.trend.trend if daily_structure else None,
            direction,
            code="daily_structure_aligned",
            label="Daily structure aligned",
            source="structure.1d.trend",
        ),
    ]
    conflicts = []
    htf_conflict = conflict_if_higher_timeframe_opposed(direction, daily_structure, "daily")
    if htf_conflict:
        conflicts.append(htf_conflict)

    reference_key = f"{ma_key}|{period}"
    return build_resolved_candidate(
        inputs,
        SetupType.MOVING_AVERAGE_RECLAIM,
        direction,
        candle.timestamp,
        reference_price=current_ma,
        reference_source=ma_key,
        reference_timestamp=None,
        reference_key=reference_key,
        hard_checks=[hard_check],
        soft_checks=soft_checks,
        conflicts=conflicts,
        invalidation_criteria=[
            f"Confirmed close back {'below' if direction == Direction.BULLISH else 'above'} {ma_key.upper()}"
        ],
        metadata={"moving_average": ma_key},
    )
