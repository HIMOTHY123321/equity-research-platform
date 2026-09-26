"""Phase 15: orchestration for the Validation Lab -- ties dataset
construction, cohort statistics, and gate evaluation together. No
business logic lives here beyond wiring (same convention every other
route-facing service module in this codebase follows)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.alerts.repository import AlertRepository
from app.decision_engine.repository import DecisionEngineRepository
from app.schemas.market_data import Timeframe
from app.validation.ai_summary import ValidationSummary, build_validation_summary
from app.validation.cohort import build_cohort_statistics
from app.validation.dataset import build_prospective_dataset
from app.validation.gate import (
    SIGNAL_GATE_V1_CRITERIA,
    SIGNAL_GATE_VERSION,
    SignalGateEvaluation,
    evaluate_signal_gate,
)
from app.validation.repository import SignalGateRepository
from app.validation.schemas import ProspectiveObservation

_SUMMARY_EVENT_TYPES = (
    "entry_conditions_met",
    "thesis_strengthening",
    "thesis_weakening",
    "invalidated",
    "exit_conditions_met",
)


def observation_status(observations: list[ProspectiveObservation]) -> dict:
    """§62: factual unresolved/resolved counts -- explains why sample
    counts grow slowly, never fabricated."""
    resolved = [o for o in observations if o.resolved]
    return {
        "total": len(observations),
        "resolved": len(resolved),
        "unresolved": len(observations) - len(resolved),
    }


def evaluate_and_persist_gate(
    alert_repository: AlertRepository,
    decision_repository: DecisionEngineRepository,
    gate_repository: SignalGateRepository,
    *,
    timeframe: Timeframe = Timeframe.ONE_HOUR,
) -> tuple[SignalGateEvaluation, list[ProspectiveObservation]]:
    observations = build_prospective_dataset(alert_repository, decision_repository)
    gate_repository.save_gate_version(SIGNAL_GATE_VERSION, SIGNAL_GATE_V1_CRITERIA.__dict__)
    evaluation = evaluate_signal_gate(observations, timeframe)
    gate_repository.save_gate_result(
        SIGNAL_GATE_VERSION,
        datetime.now(timezone.utc),
        evaluation.decision.value,
        {**evaluation.__dict__, "decision": evaluation.decision.value},
    )
    return evaluation, observations


def build_summary(
    alert_repository: AlertRepository,
    decision_repository: DecisionEngineRepository,
    gate_repository: SignalGateRepository,
    *,
    timeframe: Timeframe = Timeframe.ONE_HOUR,
    horizon_bars: int = 5,
) -> ValidationSummary:
    """Orchestrates the AI validation summary (§ AI validation summary):
    evaluates the gate (persisting it, same as get_gate already does) and
    builds one CohortStatistics per Decision Engine event type, then feeds
    both -- and only both -- into app.validation.ai_summary's deterministic
    text generator. No other data source is ever consulted."""
    evaluation, observations = evaluate_and_persist_gate(
        alert_repository, decision_repository, gate_repository, timeframe=timeframe
    )
    cohorts = {
        event_type: build_cohort_statistics(
            event_type, [o for o in observations if o.event_type == event_type], horizon_bars, timeframe
        )
        for event_type in _SUMMARY_EVENT_TYPES
    }
    return build_validation_summary(evaluation, cohorts)
