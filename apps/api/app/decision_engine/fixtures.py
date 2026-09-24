"""Phase 13.1: deterministic replay fixtures for exercising the full
DecisionPlan lifecycle without waiting for real market data to naturally
produce every state.

This module does NOT change engine behavior -- state_machine.py,
conditions.py, service.evaluate_plan, and evidence_diff.py are used exactly
as they are for live/real data. It only supplies synthetic-but-real inputs
(a small, hand-designed candle series fed through the real
build_market_snapshot pipeline) and hand-constructed DecisionPlan condition
lists (bypassing plan_builder's setup-detection-derived condition builder,
which needs a real qualified SetupCandidate) so every transition in the
lifecycle can be driven to a specific, reproducible outcome on demand.

Three scenarios, chosen to cover every transition family in the spec:
  - "strengthen_invalidate": WATCHING -> ENTRY_CONDITIONS_MET -> ACTIVE_THESIS
    -> THESIS_STRENGTHENING -> INVALIDATED
  - "exit": WATCHING -> ENTRY_CONDITIONS_MET -> ACTIVE_THESIS ->
    EXIT_CONDITIONS_MET (via a time_elapsed exit condition)
  - "expire": WATCHING -> EXPIRED (entry conditions never satisfied before
    the monitoring window closes)

Symbols are obviously synthetic (ZFXA/ZFXB/ZFXC) so they can never collide
with a real ticker in the UI or the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.ai_analysis.market_snapshot import MarketSnapshot, build_market_snapshot
from app.decision_engine.repository import DecisionEngineRepository
from app.decision_engine.schemas import (
    BarSemantics,
    ConditionOperator,
    ConditionRole,
    ConditionStatus,
    ConditionType,
    DecisionCondition,
    DecisionPlan,
    DecisionState,
    ResearchStatusLabel,
)
from app.decision_engine.service import evaluate_plan
from app.decision_engine.state_machine import PIPELINE_VERSION, build_transition
from app.market_data.provider import MarketDataProvider
from app.market_structure.schemas import Direction
from app.schemas.market_data import Candle, MarketSession, Timeframe
from app.setup_detection.schemas import SetupType

_FIXTURE_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
_BASE_VOLUME = 1_000_000.0
_STRENGTHEN_VOLUME = 3_500_000.0
_BASE_CANDLE_COUNT = 25  # > rvol_period(20) + 1, so relative_volume is always computable


def _candle(symbol: str, index: int, close: float, volume: float) -> Candle:
    timestamp = _FIXTURE_START + timedelta(days=index)
    return Candle(
        symbol=symbol,
        timeframe=Timeframe.ONE_DAY,
        timestamp=timestamp,
        session=MarketSession.REGULAR,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=volume,
    )


class _FixtureProvider(MarketDataProvider):
    """Serves one fixed, hand-designed daily candle series for one fixture
    symbol. Never returns 4h/1h data -- structure for those timeframes is
    simply INSUFFICIENT_DATA, which the real engines already handle without
    fabricating anything (exactly as a genuinely new/thin symbol would)."""

    def __init__(self, symbol: str, candles: list[Candle]) -> None:
        self._symbol = symbol
        self._candles = candles

    def get_candles(self, symbol, timeframe, limit=200, before=None):
        if symbol != self._symbol or timeframe != Timeframe.ONE_DAY:
            return []
        candles = self._candles
        if before is not None:
            candles = [c for c in candles if c.timestamp < before]
        return candles[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def _base_series(symbol: str) -> list[Candle]:
    return [_candle(symbol, i, close=100.0, volume=_BASE_VOLUME) for i in range(_BASE_CANDLE_COUNT)]


@dataclass(frozen=True)
class FixtureStep:
    """One point-in-time evaluation in a fixture scenario's timeline."""

    as_of: datetime
    label: str


@dataclass(frozen=True)
class FixtureScenario:
    name: str
    symbol: str
    direction: Direction
    candles: list[Candle]
    entry_conditions: list[DecisionCondition]
    invalidation_conditions: list[DecisionCondition]
    exit_conditions: list[DecisionCondition]
    steps: list[FixtureStep]


def _condition(
    role: ConditionRole,
    type_: ConditionType,
    description: str,
    operator: ConditionOperator,
    required_value: Optional[float],
    bar_semantics: BarSemantics = BarSemantics.COMPLETED_BAR,
) -> DecisionCondition:
    return DecisionCondition(
        id=str(uuid.uuid4()),
        role=role,
        type=type_,
        description=description,
        timeframe=Timeframe.ONE_DAY,
        bar_semantics=bar_semantics,
        operator=operator,
        required_value=required_value,
        actual_value=None,
        status=ConditionStatus.PENDING,
        evaluated_at=None,
        source_evidence_ref=None,
    )


def _strengthen_invalidate_scenario() -> FixtureScenario:
    symbol = "ZFXA"
    candles = _base_series(symbol)
    breakout_idx = len(candles)
    candles.append(_candle(symbol, breakout_idx, close=112.0, volume=_BASE_VOLUME))
    strengthen_idx = breakout_idx + 1
    for i in range(3):
        candles.append(_candle(symbol, strengthen_idx + i, close=112.0 + i, volume=_STRENGTHEN_VOLUME))
    invalidate_idx = strengthen_idx + 3
    candles.append(_candle(symbol, invalidate_idx, close=90.0, volume=_BASE_VOLUME))

    # +1 day (not +1 minute): a daily candle only becomes "completed" once
    # its own exchange trading date is strictly behind `as_of`'s trading
    # date (see app.features.common.is_candle_complete) -- a same-day
    # as_of would leave the candle looking still-forming and silently shift
    # every step's "latest candle" back by one, which is exactly the
    # anti-lookahead discipline this fixture must respect, not route around.
    steps = [
        FixtureStep(candles[breakout_idx].timestamp + timedelta(days=1), "entry breakout closes above 110"),
        FixtureStep(candles[strengthen_idx].timestamp + timedelta(days=1), "volume surge begins"),
        FixtureStep(
            candles[invalidate_idx].timestamp + timedelta(days=1), "close breaks below invalidation level"
        ),
    ]
    return FixtureScenario(
        name="strengthen_invalidate",
        symbol=symbol,
        direction=Direction.BULLISH,
        candles=candles,
        entry_conditions=[
            _condition(
                ConditionRole.ENTRY,
                ConditionType.CLOSE_ABOVE,
                "1d close above 110.00",
                ConditionOperator.GTE,
                110.0,
            )
        ],
        invalidation_conditions=[
            _condition(
                ConditionRole.INVALIDATION,
                ConditionType.CLOSE_BELOW,
                "1d close below 95.00 (invalidation buffer)",
                ConditionOperator.LTE,
                95.0,
            )
        ],
        exit_conditions=[],
        steps=steps,
    )


def _exit_scenario() -> FixtureScenario:
    symbol = "ZFXB"
    candles = _base_series(symbol)
    breakout_idx = len(candles)
    candles.append(_candle(symbol, breakout_idx, close=112.0, volume=_BASE_VOLUME))

    activation_as_of = candles[breakout_idx].timestamp + timedelta(days=1)
    steps = [
        FixtureStep(activation_as_of, "entry breakout closes above 110"),
        FixtureStep(activation_as_of + timedelta(minutes=5), "monitoring window elapses"),
    ]
    return FixtureScenario(
        name="exit",
        symbol=symbol,
        direction=Direction.BULLISH,
        candles=candles,
        entry_conditions=[
            _condition(
                ConditionRole.ENTRY,
                ConditionType.CLOSE_ABOVE,
                "1d close above 110.00",
                ConditionOperator.GTE,
                110.0,
            )
        ],
        invalidation_conditions=[
            _condition(
                ConditionRole.INVALIDATION,
                ConditionType.CLOSE_BELOW,
                "1d close below 10.00 (unreachable in this fixture)",
                ConditionOperator.LTE,
                10.0,
            )
        ],
        exit_conditions=[
            _condition(
                ConditionRole.EXIT,
                ConditionType.TIME_ELAPSED,
                "Monitoring window of 2 minutes elapsed without invalidation",
                ConditionOperator.GTE,
                2.0,
                bar_semantics=BarSemantics.TICK,
            )
        ],
        steps=steps,
    )


def _expire_scenario() -> FixtureScenario:
    symbol = "ZFXC"
    candles = _base_series(symbol)
    start_as_of = candles[-1].timestamp + timedelta(days=1)
    steps = [
        FixtureStep(start_as_of, "monitoring begins"),
        FixtureStep(start_as_of + timedelta(minutes=5), "monitoring window elapses without entry"),
    ]
    return FixtureScenario(
        name="expire",
        symbol=symbol,
        direction=Direction.BULLISH,
        candles=candles,
        entry_conditions=[
            _condition(
                ConditionRole.ENTRY,
                ConditionType.CLOSE_ABOVE,
                "1d close above 1000.00 (unreachable in this fixture)",
                ConditionOperator.GTE,
                1000.0,
            )
        ],
        invalidation_conditions=[
            _condition(
                ConditionRole.INVALIDATION,
                ConditionType.CLOSE_BELOW,
                "1d close below 1.00 (unreachable in this fixture)",
                ConditionOperator.LTE,
                1.0,
            )
        ],
        exit_conditions=[
            _condition(
                ConditionRole.EXIT,
                ConditionType.TIME_ELAPSED,
                "Monitoring window of 2 minutes elapsed without entry",
                ConditionOperator.GTE,
                2.0,
                bar_semantics=BarSemantics.TICK,
            )
        ],
        steps=steps,
    )


FIXTURE_SCENARIOS: dict[str, FixtureScenario] = {
    s.name: s for s in (_strengthen_invalidate_scenario(), _exit_scenario(), _expire_scenario())
}


def fixture_provider(scenario: FixtureScenario) -> MarketDataProvider:
    return _FixtureProvider(scenario.symbol, scenario.candles)


def fixture_snapshot_at(
    scenario: FixtureScenario, as_of: datetime, provider: Optional[MarketDataProvider] = None
) -> MarketSnapshot:
    """The real build_market_snapshot pipeline, over the fixture's synthetic
    candles. `provider` is overridable so the anti-lookahead spot check can
    pass an EXTENDED provider (more future candles) and confirm truncation
    to `as_of` makes the result identical regardless."""
    resolved_provider = provider or fixture_provider(scenario)
    return build_market_snapshot(scenario.symbol, Timeframe.ONE_DAY, resolved_provider, as_of, now=as_of)


def build_fixture_plan(scenario: FixtureScenario, as_of: datetime) -> DecisionPlan:
    """Mirrors plan_builder.build_decision_plan's DETECTED -> EVALUATING ->
    WATCHING sequence exactly (same state_machine.build_transition calls),
    just seeded with the scenario's hand-picked conditions instead of
    conditions derived from a real qualified SetupCandidate."""
    plan = DecisionPlan(
        decision_plan_id=f"{scenario.name}-{uuid.uuid4()}",
        symbol=scenario.symbol,
        timeframe=Timeframe.ONE_DAY,
        setup_id=f"fixture:{scenario.name}",
        setup_type=SetupType.RANGE_BREAKOUT,
        direction=scenario.direction,
        created_at=as_of,
        as_of=as_of,
        state=DecisionState.DETECTED,
        entry_conditions=scenario.entry_conditions,
        invalidation_conditions=scenario.invalidation_conditions,
        exit_conditions=scenario.exit_conditions,
        monitoring_conditions=[],
        transitions=[],
        research_status=[ResearchStatusLabel.RESEARCH_MONITORING_ONLY],
        source_setup_snapshot_id=f"fixture:{scenario.name}",
        pipeline_version=PIPELINE_VERSION,
    )
    evaluating_transition = build_transition(
        plan, DecisionState.EVALUATING, reason="Fixture scenario seeded; beginning evaluation", as_of=as_of
    )
    plan = plan.model_copy(update={"state": DecisionState.EVALUATING, "transitions": [evaluating_transition]})
    watching_transition = build_transition(
        plan, DecisionState.WATCHING, reason="Fixture entry/invalidation/exit conditions defined", as_of=as_of
    )
    return plan.model_copy(
        update={"state": DecisionState.WATCHING, "transitions": [*plan.transitions, watching_transition]}
    )


def run_fixture_scenario(
    scenario_name: str, repository: Optional[DecisionEngineRepository] = None
) -> list[DecisionPlan]:
    """Steps a fixture plan through every `as_of` in its scenario using the
    REAL, unmodified evaluate_plan -- the exact function live evaluation and
    replay both use. Returns every intermediate plan state (one per step) so
    a caller can inspect the full lifecycle, not just the final state. If a
    repository is given, each step's plan/transitions/conditions are
    persisted through it, so the existing /api/decisions endpoints and the
    existing Decision Monitor UI can display the fixture with zero new
    frontend code."""
    scenario = FIXTURE_SCENARIOS[scenario_name]
    provider = fixture_provider(scenario)
    plan = build_fixture_plan(scenario, scenario.steps[0].as_of)
    if repository is not None:
        repository.save_plan(plan)
        for t in plan.transitions:
            repository.record_transition(t)

    history = [plan]
    for step in scenario.steps:
        snapshot = fixture_snapshot_at(scenario, step.as_of, provider)
        result = evaluate_plan(plan, snapshot, step.as_of)
        plan = result.plan
        history.append(plan)
        if repository is not None:
            repository.save_plan(plan)
            for t in result.transitions:
                repository.record_transition(t)
            if result.evaluated_conditions:
                repository.record_condition_evaluations(plan.decision_plan_id, result.evaluated_conditions)
            if result.evidence_diff is not None:
                repository.record_evidence_diff(result.evidence_diff)
    return history
