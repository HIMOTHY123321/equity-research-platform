"""Phase 15 §7/§8/§9: independence/episode grouping for
`ProspectiveObservation`s -- the same philosophy as
`app.research_intelligence.episodes`/`independence` (raw -> episode ->
purged, least to most conservative), reimplemented directly against
`ProspectiveObservation`'s own fields rather than forcing an adapter onto
`SetupLedgerEntry`-typed functions that assume a nested
`detection_snapshot`/`candidate_candle_timestamp` shape this package's
objects don't have.

Grouping key mirrors app.research_intelligence.episodes exactly:
(symbol, setup_type, direction, timeframe) -- observations sharing a
decision_plan_id are always the same episode (they came from the same
underlying DecisionPlan), which is a strictly *more* precise signal than
episodes.py has available for historical ledger entries.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.schemas.market_data import Timeframe
from app.setup_detection.detectors._common import bar_duration_seconds
from app.validation.schemas import ProspectiveObservation


def episode_key(observation: ProspectiveObservation) -> tuple:
    return (observation.symbol, observation.setup_type, observation.direction, observation.timeframe)


def episode_level_sample(observations: list[ProspectiveObservation]) -> list[ProspectiveObservation]:
    """One representative observation per (episode key, decision_plan_id)
    -- since every observation with a decision_plan_id already belongs to
    exactly one plan, the plan id itself is the finest-grained episode
    identity available here. Representative = earliest by
    alert_occurred_at, chosen at detection time, never by outcome."""
    by_episode: dict[tuple, ProspectiveObservation] = {}
    for observation in observations:
        key = (episode_key(observation), observation.decision_plan_id or observation.observation_id)
        existing = by_episode.get(key)
        if existing is None or observation.alert_occurred_at < existing.alert_occurred_at:
            by_episode[key] = observation
    return list(by_episode.values())


def purged_sample(
    observations: list[ProspectiveObservation], horizon_bars: int, timeframe: Timeframe
) -> list[ProspectiveObservation]:
    """Deterministic, greedy, chronological purge -- identical algorithm to
    app.research_intelligence.independence.purged_sample, operating on
    `alert_occurred_at`/`observation_id` instead of
    `candidate_candle_timestamp`/`setup_id`."""
    window = timedelta(seconds=bar_duration_seconds(timeframe) * horizon_bars)
    ordered = sorted(observations, key=lambda o: (o.alert_occurred_at, o.observation_id))

    selected: list[ProspectiveObservation] = []
    excluded_until: dict[str, Optional[datetime]] = {}
    for observation in ordered:
        blocked_until = excluded_until.get(observation.symbol)
        if blocked_until is not None and observation.alert_occurred_at <= blocked_until:
            continue
        selected.append(observation)
        window_end = observation.alert_occurred_at + window
        if blocked_until is None or window_end > blocked_until:
            excluded_until[observation.symbol] = window_end
    return selected


def sample_counts(
    observations: list[ProspectiveObservation], horizon_bars: int, timeframe: Timeframe
) -> tuple[int, int, int]:
    """Returns (raw_n, independent_n, purged_n) -- report all three,
    never just one (§7)."""
    raw_n = len(observations)
    independent_n = len(episode_level_sample(observations))
    purged_n = len(purged_sample(observations, horizon_bars, timeframe))
    return raw_n, independent_n, purged_n
