"""Phase 15 §26/§27/§75/§76: the Signal Validation Gate must never PASS
on a handful of successful alerts, must remain NOT_ENOUGH_DATA until real
breadth/duration criteria are met, and must never touch the Phase 9
RANKING GATE."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.market_data import Timeframe
from app.validation.gate import (
    SignalGateCriteria,
    SignalGateDecision,
    evaluate_signal_gate,
)
from app.validation.schemas import DatasetOrigin, ProspectiveObservation

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _observation(
    obs_id: str,
    day_offset: int,
    symbol: str,
    return_5: float | None,
    decision_plan_id: str | None = None,
) -> ProspectiveObservation:
    return ProspectiveObservation(
        observation_id=obs_id,
        alert_id=obs_id,
        decision_plan_id=decision_plan_id or f"plan-{obs_id}",
        symbol=symbol,
        setup_type="breakout_retest",
        direction="bullish",
        timeframe="1h",
        event_type="entry_conditions_met",
        alert_occurred_at=_START + timedelta(days=day_offset),
        origin=DatasetOrigin.PROSPECTIVE,
        pipeline_version="test",
        resolved=True,
        return_5=return_5,
    )


def test_empty_dataset_is_not_enough_data():
    evaluation = evaluate_signal_gate([], Timeframe.ONE_HOUR)
    assert evaluation.decision == SignalGateDecision.NOT_ENOUGH_DATA
    assert evaluation.reasons


def test_a_handful_of_successful_alerts_cannot_pass():
    # 5 observations, 1 symbol, 5 days -- far below any reasonable
    # breadth/duration requirement, even though every single one is a
    # strong positive outcome.
    observations = [_observation(f"o{i}", i, "NVDA", return_5=2.0) for i in range(5)]
    evaluation = evaluate_signal_gate(observations, Timeframe.ONE_HOUR)
    assert evaluation.decision == SignalGateDecision.NOT_ENOUGH_DATA


def test_stable_replicated_fixture_satisfying_every_criterion_passes():
    criteria = SignalGateCriteria(
        min_independent_episodes=10,
        min_symbols=3,
        max_single_symbol_share=0.5,
        min_observation_days=10,
        max_cost_bps_for_survival=5.0,
    )
    symbols = ["SPY", "QQQ", "NVDA"]
    observations = [
        _observation(f"o{i}", i, symbols[i % 3], return_5=1.0, decision_plan_id=f"plan-{i}")
        for i in range(30)
    ]
    evaluation = evaluate_signal_gate(observations, Timeframe.ONE_HOUR, criteria=criteria)
    assert evaluation.decision == SignalGateDecision.PASS


def test_symbol_concentration_too_high_cannot_pass():
    criteria = SignalGateCriteria(
        min_independent_episodes=10, min_symbols=2, max_single_symbol_share=0.5, min_observation_days=10
    )
    # 90% NVDA -- fails the concentration requirement even with a
    # positive median effect and otherwise-sufficient breadth.
    observations = [
        _observation(f"o{i}", i, "NVDA" if i < 27 else "SPY", return_5=1.0, decision_plan_id=f"plan-{i}")
        for i in range(30)
    ]
    evaluation = evaluate_signal_gate(observations, Timeframe.ONE_HOUR, criteria=criteria)
    assert evaluation.decision == SignalGateDecision.FAIL
    assert evaluation.max_symbol_share is not None
    assert evaluation.max_symbol_share > 0.5


def test_cost_adjusted_edge_disappearing_cannot_pass():
    criteria = SignalGateCriteria(
        min_independent_episodes=10,
        min_symbols=3,
        max_single_symbol_share=0.5,
        min_observation_days=10,
        max_cost_bps_for_survival=5.0,
        require_cost_survival=True,
    )
    symbols = ["SPY", "QQQ", "NVDA"]
    # A tiny 0.02% raw edge does not survive a 5bps (0.05%) cost haircut.
    observations = [
        _observation(f"o{i}", i, symbols[i % 3], return_5=0.02, decision_plan_id=f"plan-{i}")
        for i in range(30)
    ]
    evaluation = evaluate_signal_gate(observations, Timeframe.ONE_HOUR, criteria=criteria)
    assert evaluation.decision == SignalGateDecision.FAIL


def test_gate_never_produces_a_ranking_gate_field():
    """§76: the Signal Validation Gate evaluation must not carry any
    field that could be mistaken for -- or used to silently flip -- the
    independent Phase 9 RANKING GATE."""
    evaluation = evaluate_signal_gate([], Timeframe.ONE_HOUR)
    assert not hasattr(evaluation, "ranking_gate_status")
    assert "ranking" not in evaluation.__dict__
