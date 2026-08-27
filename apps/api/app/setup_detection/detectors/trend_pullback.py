"""Trend pullback (#16): a structural pattern, not a discretionary "looks
like a pullback" heuristic. Requires an established trend, a retracement
that actually reaches a real support/resistance reference, and confirmation
that the trend's own structural invalidation level (the most recent HL for
a bullish trend, LH for bearish) was not broken.

Hard/soft checks are evaluated against the latest completed candle (is the
current state a valid pullback right now), but the candidate's *identity*
is anchored to the start of the current streak of bars sharing the same
broken/unbroken state relative to the invalidation level -- not to
"whichever bar is latest" -- so the same pullback episode (held retracement
*or* an ongoing structural break) updates one lifecycle rather than minting
a new candidate every bar it continues to hold. See docs/decisions/0009 for
the real duplicate-signal bug this replaces (found in Phase 7 replay,
deliberately not rushed then) and the episode-boundary design.
"""

from __future__ import annotations

from app.market_structure.schemas import Direction, TrendClass
from app.setup_detection.conflicts import conflict_if_higher_timeframe_opposed
from app.setup_detection.context import DetectorInputs
from app.setup_detection.detectors._common import build_resolved_candidate
from app.setup_detection.schemas import EvidenceCheck, RuleType, SetupCandidate, SetupType


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    structure = inputs.structure_by_timeframe.get(inputs.timeframe)
    if structure is None or not inputs.candles:
        return []

    candidates: list[SetupCandidate] = []
    latest = inputs.candles[-1]

    for direction in (Direction.BULLISH, Direction.BEARISH):
        candidate = _check_direction(inputs, structure, latest, direction)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


# A safety cap only -- not a semantic bound. The real episode boundaries
# are structural (a close-based break of the invalidation level, or walking
# back past the moment the invalidation reference itself became current);
# this just prevents a pathological unbounded backward scan. It must stay
# far larger than any realistic episode length, or an episode that outlives
# it would have its identity drift forward by one bar every step past the
# cap -- reintroducing the exact duplicate-signal bug this fix exists to
# remove. 2000 bars is ~730 hours (~4 months of 1H trading) with room to
# spare for any timeframe this detector runs on.
_MAX_EPISODE_LOOKBACK_BARS = 2000


def _is_broken(candle, direction, invalidation_level) -> bool:
    return not (
        (candle.close > invalidation_level)
        if direction == Direction.BULLISH
        else (candle.close < invalidation_level)
    )


def _episode_start_index(candles, direction, invalidation_level, invalidation_pivot_timestamp):
    """The first bar (walking backward from the latest) that shares the
    latest bar's broken/unbroken state relative to `invalidation_level`.
    Grouping is symmetric on purpose: a held (unbroken) retracement groups
    into one episode, but so does a run of bars where the level stays
    broken -- otherwise every bar of a multi-hour break mints its own
    rejected candidate, which is the same duplicate-signal bug in a
    different state (found via real SPY 1H replay: 2026-08-14 stayed
    continuously broken from 09:30 to 15:30, and without this symmetry
    each of those bars produced a distinct id). A state *change* -- broken
    to unbroken or vice versa -- is the genuine episode boundary. Walking
    back past the swing's own pivot candle (the earliest instant that
    specific price level exists as a value at all -- deliberately the
    swing's `pivot_timestamp`, not its later `confirmed_at`: bounding on
    confirmed_at was tried first and was wrong, since confirmed_at is
    typically *after* the very retracement bars this walk needs to
    include, collapsing the walk to zero steps every time) also ends it."""
    idx = len(candles) - 1
    latest_broken = _is_broken(candles[idx], direction, invalidation_level)
    steps = 0
    while idx - 1 >= 0 and steps < _MAX_EPISODE_LOOKBACK_BARS:
        prev = candles[idx - 1]
        if prev.timestamp < invalidation_pivot_timestamp:
            break
        if _is_broken(prev, direction, invalidation_level) != latest_broken:
            break
        idx -= 1
        steps += 1
    return idx


def _check_direction(inputs, structure, latest, direction):
    expected_trend = TrendClass.BULLISH if direction == Direction.BULLISH else TrendClass.BEARISH
    invalidation_swing = (
        structure.latest_higher_low if direction == Direction.BULLISH else structure.latest_lower_high
    )
    reference_zone = (
        inputs.levels_snapshot.nearest_support
        if direction == Direction.BULLISH
        else inputs.levels_snapshot.nearest_resistance
    )

    # Data-quality gate (#22): without a structural invalidation reference or
    # a nearby zone to measure the retracement against, this can't be
    # evaluated honestly -- skip rather than guess.
    if invalidation_swing is None or reference_zone is None:
        return None

    trend_check = EvidenceCheck(
        code="trend_established",
        label=f"{'Bullish' if direction == Direction.BULLISH else 'Bearish'} trend established",
        rule_type=RuleType.HARD,
        passed=structure.trend.trend == expected_trend,
        source=f"structure.{inputs.timeframe.value}.trend",
    )

    reference_price = reference_zone.representative_price
    touch_price = latest.low if direction == Direction.BULLISH else latest.high
    distance_percent = abs(touch_price - reference_price) / reference_price * 100
    proximity_check = EvidenceCheck(
        code="retraced_into_reference_zone",
        label=f"Pullback reached {'support' if direction == Direction.BULLISH else 'resistance'} "
        f"({distance_percent:.2f}% away)",
        rule_type=RuleType.HARD,
        passed=distance_percent <= inputs.config.pullback_proximity_percent,
        actual=distance_percent,
        required=inputs.config.pullback_proximity_percent,
        source="levels.nearest_support" if direction == Direction.BULLISH else "levels.nearest_resistance",
    )

    invalidation_level = invalidation_swing.price
    no_break_check = EvidenceCheck(
        code="structural_invalidation_not_broken",
        label=f"Close has not broken the most recent "
        f"{'higher low' if direction == Direction.BULLISH else 'lower high'} at {invalidation_level:.2f}",
        rule_type=RuleType.HARD,
        passed=(latest.close > invalidation_level)
        if direction == Direction.BULLISH
        else (latest.close < invalidation_level),
        actual=latest.close,
        required=invalidation_level,
        source="structure.latest_higher_low"
        if direction == Direction.BULLISH
        else "structure.latest_lower_high",
    )

    confirmation_check = EvidenceCheck(
        code="confirmation_candle_direction",
        label=f"Latest completed candle closed {'bullish' if direction == Direction.BULLISH else 'bearish'}",
        rule_type=RuleType.SOFT,
        passed=(latest.close > latest.open)
        if direction == Direction.BULLISH
        else (latest.close < latest.open),
        source="candle.open_close",
    )

    hard_checks = [trend_check, proximity_check, no_break_check]
    if not any(c.passed for c in hard_checks[:1]):
        # If the trend itself isn't even established in this direction,
        # this isn't a meaningful rejected candidate -- it's just not
        # applicable, so skip rather than clutter rejected_candidates.
        return None

    conflicts = []
    higher_conflict = conflict_if_higher_timeframe_opposed(direction, structure, inputs.timeframe.value)
    if higher_conflict:
        conflicts.append(higher_conflict)

    episode_start_idx = _episode_start_index(
        inputs.candles, direction, invalidation_level, invalidation_swing.pivot_timestamp
    )
    episode_start_candle = inputs.candles[episode_start_idx]

    reference_key = f"pullback|{invalidation_swing.pivot_timestamp.isoformat()}"
    return build_resolved_candidate(
        inputs,
        SetupType.TREND_PULLBACK,
        direction,
        episode_start_candle.timestamp,
        reference_price=reference_price,
        reference_source="nearest_support" if direction == Direction.BULLISH else "nearest_resistance",
        reference_timestamp=invalidation_swing.pivot_timestamp,
        reference_key=reference_key,
        hard_checks=hard_checks,
        soft_checks=[confirmation_check],
        conflicts=conflicts,
        invalidation_criteria=[
            f"Confirmed close {'below' if direction == Direction.BULLISH else 'above'} "
            f"{invalidation_level:.2f} "
            f"(the {'higher low' if direction == Direction.BULLISH else 'lower high'} this trend depends on)"
        ],
    )
