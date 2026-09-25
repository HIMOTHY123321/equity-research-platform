"""Deterministic dedup-key computation (§6/§7 of the Phase 14 spec).

The dedup key is what makes exactly-once enforcement possible at the
database layer (a UNIQUE constraint on AlertEventRecord.dedup_key) instead
of relying on an in-memory set, which would not survive a restart and would
not be safe under concurrent evaluations (§47).

Two families of key:
  * transition alerts -- one alert can ever exist for a given DecisionPlan
    moving through a given DecisionTransition, full stop, forever. No time
    bucketing: replaying the exact same transition later must still collide.
  * everything else (condition flips, conflicts, catalysts, data-freshness,
    stream-health) -- identity is `symbol + alert_type + identity string`,
    bucketed by `source_timestamp` at a cooldown granularity so repeated
    polls that keep observing the *same* underlying state (e.g. "still
    stale") don't create a new row every poll, while a genuinely new
    occurrence (a new source_timestamp bucket) does. Transition-adjacent
    alert types are exempt from cooldown bucketing per §7 ("cooldowns must
    NEVER suppress INVALIDATED/EXIT CONDITIONS MET/ENTRY CONDITIONS MET") --
    those go through the transition-key path instead, which has no bucket
    at all, so this function is never even called with a bucket for them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.alerts.schemas import AlertType

# How often a persistently-true non-transition condition (e.g. "still
# stale") is allowed to re-alert. Chosen to be long enough to avoid poll-
# frequency spam but short enough that a still-relevant condition is not
# silent for the rest of the day.
DEFAULT_COOLDOWN = timedelta(hours=1)


def transition_dedup_key(decision_plan_id: str, transition_id: str, alert_type: AlertType) -> str:
    return f"transition:{decision_plan_id}:{transition_id}:{alert_type.value}"


def _bucket(source_timestamp: datetime, cooldown: timedelta) -> str:
    ts = source_timestamp.astimezone(timezone.utc) if source_timestamp.tzinfo else source_timestamp.replace(
        tzinfo=timezone.utc
    )
    bucket_index = int(ts.timestamp() // cooldown.total_seconds())
    return str(bucket_index)


def condition_dedup_key(
    symbol: str,
    alert_type: AlertType,
    identity: str,
    source_timestamp: datetime,
    *,
    cooldown: timedelta = DEFAULT_COOLDOWN,
) -> str:
    """`identity` disambiguates within (symbol, alert_type) -- e.g. a
    condition_id for CONDITION_PASSED/FAILED, a conflict signature for
    CONFLICT_ADDED/REMOVED, a catalyst episode id for CATALYST_UPDATE, the
    literal string "freshness" for DATA_STALE/RECOVERED, or a provider name
    for STREAM_DISCONNECTED/RECONNECTED."""
    bucket = _bucket(source_timestamp, cooldown)
    return f"condition:{symbol}:{alert_type.value}:{identity}:{bucket}"
