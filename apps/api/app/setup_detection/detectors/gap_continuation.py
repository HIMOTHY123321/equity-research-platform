"""Gap continuation (#13). Reuses Phase 3's gap definition
(`FeatureSnapshot.gap`) and session tracking (`FeatureSnapshot.session`)
directly rather than recomputing a competing gap calculation. Not every gap
is tradable -- the minimum-size and mostly-filled thresholds are both
configurable, not hard-assumed.
"""

from __future__ import annotations

from app.features.common import FeatureStatus
from app.market_data.sessions import exchange_trading_date
from app.market_structure.schemas import Direction, Timeframe
from app.setup_detection.conflicts import conflict_if_higher_timeframe_opposed
from app.setup_detection.context import DetectorInputs
from app.setup_detection.detectors._common import build_resolved_candidate
from app.setup_detection.evidence import check_rvol, check_trend_alignment
from app.setup_detection.schemas import EvidenceCheck, RuleType, SetupCandidate, SetupType


def detect(inputs: DetectorInputs) -> list[SetupCandidate]:
    gap = inputs.feature_snapshot.gap
    session = inputs.feature_snapshot.session
    if gap.status != FeatureStatus.OK or gap.gap_percent is None or gap.direction not in ("up", "down"):
        return []
    if session.status != FeatureStatus.OK or session.latest_price is None:
        return []
    if abs(gap.gap_percent) < inputs.config.min_gap_percent_for_continuation:
        return []
    if not inputs.candles:
        return []

    direction = Direction.BULLISH if gap.direction == "up" else Direction.BEARISH
    gap_size = abs(gap.session_open - gap.previous_close) if gap.session_open is not None else None
    if not gap_size:
        return []

    if direction == Direction.BULLISH:
        retracement = max(0.0, gap.session_open - (session.session_low_so_far or gap.session_open))
        still_holding = session.latest_price >= gap.session_open
    else:
        retracement = max(0.0, (session.session_high_so_far or gap.session_open) - gap.session_open)
        still_holding = session.latest_price <= gap.session_open

    fill_percent = min(100.0, retracement / gap_size * 100)

    hard_checks = [
        EvidenceCheck(
            code="gap_size_sufficient",
            label=f"Gap {gap.gap_percent:+.2f}% (minimum {inputs.config.min_gap_percent_for_continuation}%)",
            rule_type=RuleType.HARD,
            passed=True,
            actual=abs(gap.gap_percent),
            required=inputs.config.min_gap_percent_for_continuation,
            source="features.gap",
        ),
        EvidenceCheck(
            code="gap_not_mostly_filled",
            label=f"Gap {fill_percent:.0f}% filled (limit {inputs.config.gap_mostly_filled_percent:.0f}%)",
            rule_type=RuleType.HARD,
            passed=fill_percent < inputs.config.gap_mostly_filled_percent,
            actual=fill_percent,
            required=inputs.config.gap_mostly_filled_percent,
            source="features.session",
        ),
        EvidenceCheck(
            code="gap_structure_holding",
            label=f"Price still {'above' if direction == Direction.BULLISH else 'below'} session open",
            rule_type=RuleType.HARD,
            passed=still_holding,
            actual=session.latest_price,
            required=gap.session_open,
            source="features.session.latest_price",
        ),
    ]

    daily_structure = inputs.structure_by_timeframe.get(Timeframe.ONE_DAY)
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

    # Anchored to the session-open bar, not "whichever bar is latest" (#26):
    # the same gap continues to hold or fail across every bar of the same
    # trading day, so the candidate's identity must stay fixed for the
    # whole day -- otherwise every hourly bar re-evaluating the same gap
    # would mint a brand-new candidate, discovered as a real duplicate-
    # signal bug when replay (Phase 7) called this detector repeatedly
    # across a single gapped day. Matches gap_fill.py's existing convention.
    today = exchange_trading_date(inputs.as_of)
    todays_candles = sorted(
        (c for c in inputs.candles if exchange_trading_date(c.timestamp) == today), key=lambda c: c.timestamp
    )
    candidate_timestamp = todays_candles[0].timestamp if todays_candles else inputs.candles[-1].timestamp

    return [
        build_resolved_candidate(
            inputs,
            SetupType.GAP_CONTINUATION,
            direction,
            candidate_timestamp,
            reference_price=gap.session_open,
            reference_source="session_open",
            reference_timestamp=None,
            reference_key=f"gap_continuation|{gap.session_open}",
            hard_checks=hard_checks,
            soft_checks=soft_checks,
            conflicts=conflicts,
            invalidation_criteria=[
                f"Gap fills past {inputs.config.gap_mostly_filled_percent:.0f}%, "
                f"or price closes back through {gap.session_open:.2f}"
            ],
            metadata={"gap_percent": gap.gap_percent, "fill_percent": fill_percent},
        )
    ]
