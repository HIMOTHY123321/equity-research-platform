"""Drives a DecisionPlan's lifecycle across a sequence of historical `as_of`
points using the exact same `evaluate_plan` pass live evaluation uses --
"live" and "replay" are the same code path at different `as_of` values,
never two separate implementations (mirrors app.ai_analysis.market_snapshot
.build_market_snapshot's own live/historical unification).

Anti-lookahead is enforced entirely by `build_market_snapshot`'s own strict
`< as_of` candle truncation (see market_snapshot.py) -- this module adds no
additional truncation logic, only iterates `as_of` points in order and
threads the plan returned by one step into the next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.ai_analysis.market_snapshot import build_market_snapshot
from app.decision_engine.schemas import DecisionPlan, DecisionTransition
from app.decision_engine.service import evaluate_plan
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import Timeframe


@dataclass(frozen=True)
class ReplayStep:
    as_of: datetime
    plan: DecisionPlan
    transitions: list[DecisionTransition]


@dataclass(frozen=True)
class ReplayResult:
    steps: list[ReplayStep] = field(default_factory=list)

    @property
    def final_plan(self) -> DecisionPlan:
        return self.steps[-1].plan

    @property
    def transition_sequence(self) -> list[tuple[str, str]]:
        """A compact, comparable fingerprint of the full lifecycle -- exactly
        what replay-vs-replay and replay-vs-live parity tests diff."""
        return [
            (t.from_state.value if t.from_state else "", t.to_state.value)
            for step in self.steps
            for t in step.transitions
        ]


def run_replay(
    initial_plan: DecisionPlan,
    as_of_points: list[datetime],
    symbol: str,
    timeframe: Timeframe,
    provider: MarketDataProvider,
) -> ReplayResult:
    """`as_of_points` must be strictly increasing and each must be a real
    completed-candle instant the evaluation is entitled to see -- this
    function does not enforce ordering itself (callers such as
    DecisionEngineService already only ever call this at real completed-bar
    instants), it simply never looks past whichever `as_of` is currently
    being processed."""
    plan = initial_plan
    steps: list[ReplayStep] = []
    for as_of in as_of_points:
        snapshot = build_market_snapshot(symbol, timeframe, provider, as_of, now=as_of)
        result = evaluate_plan(plan, snapshot, as_of)
        plan = result.plan
        steps.append(ReplayStep(as_of=as_of, plan=plan, transitions=result.transitions))
    return ReplayResult(steps=steps)
