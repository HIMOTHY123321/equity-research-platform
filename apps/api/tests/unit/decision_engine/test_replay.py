from __future__ import annotations

from datetime import timedelta

from app.decision_engine.plan_builder import build_decision_plan
from app.decision_engine.replay import run_replay
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import FakeMarketDataProvider
from tests.unit.decision_engine.conftest import spy_snapshot


def _watching_plan_and_as_of():
    snapshot = spy_snapshot()
    setup = next(
        s
        for s in snapshot.setup_snapshot.qualified_setups
        if len([c for c in s.soft_checks if c.passed]) >= 1
        and not any(c.severity.value == "major" for c in s.conflicts)
    )
    plan = build_decision_plan(setup, as_of=snapshot.as_of)
    return plan, snapshot.as_of


def _as_of_sequence(start, n=5, step_hours=1):
    return [start + timedelta(hours=i * step_hours) for i in range(n)]


def test_replay_is_deterministic_across_repeated_runs():
    plan, start = _watching_plan_and_as_of()
    as_of_points = _as_of_sequence(start)
    provider = FakeMarketDataProvider()

    result_1 = run_replay(plan, as_of_points, "SPY", Timeframe.ONE_HOUR, provider)
    result_2 = run_replay(plan, as_of_points, "SPY", Timeframe.ONE_HOUR, provider)

    assert result_1.transition_sequence == result_2.transition_sequence
    assert result_1.final_plan.state == result_2.final_plan.state


def test_replay_transitions_only_use_data_available_at_their_as_of():
    # Every transition's `as_of` must be <= the as_of point it was produced
    # at, and steps must never see the market_data_cutoff exceed their own
    # as_of -- the direct, mechanically-checkable form of "no future data."
    plan, start = _watching_plan_and_as_of()
    as_of_points = _as_of_sequence(start)
    provider = FakeMarketDataProvider()

    result = run_replay(plan, as_of_points, "SPY", Timeframe.ONE_HOUR, provider)

    for step in result.steps:
        for transition in step.transitions:
            assert transition.as_of <= step.as_of
            assert transition.occurred_at <= step.as_of


def test_extending_history_beyond_a_step_does_not_change_that_steps_transitions():
    # Anti-lookahead: two replays that agree on every as_of point up to some
    # index N must produce IDENTICAL transitions through index N, regardless
    # of what happens at later as_of points -- a later candle must never
    # retroactively rewrite an earlier decision.
    plan, start = _watching_plan_and_as_of()
    short_points = _as_of_sequence(start, n=3)
    long_points = _as_of_sequence(start, n=6)
    provider = FakeMarketDataProvider()

    short_result = run_replay(plan, short_points, "SPY", Timeframe.ONE_HOUR, provider)
    long_result = run_replay(plan, long_points, "SPY", Timeframe.ONE_HOUR, provider)

    short_prefix = short_result.transition_sequence
    long_prefix_through_same_point = [
        t
        for step in long_result.steps[: len(short_points)]
        for t in [(x.from_state.value if x.from_state else "", x.to_state.value) for x in step.transitions]
    ]
    assert short_prefix == long_prefix_through_same_point


def test_replay_matches_live_evaluate_plan_for_the_same_as_of():
    # "Live" is replay run at as_of=now -- the same evaluate_plan pass, not
    # a structurally different code path (mirrors build_market_snapshot's
    # own live/historical unification).
    from app.ai_analysis.market_snapshot import build_market_snapshot
    from app.decision_engine.service import evaluate_plan

    plan, start = _watching_plan_and_as_of()
    provider = FakeMarketDataProvider()

    live_snapshot = build_market_snapshot("SPY", Timeframe.ONE_HOUR, provider, start, now=start)
    live_result = evaluate_plan(plan, live_snapshot, start)

    replay_result = run_replay(plan, [start], "SPY", Timeframe.ONE_HOUR, provider)

    assert replay_result.final_plan.state == live_result.plan.state
    assert replay_result.transition_sequence == [
        (t.from_state.value if t.from_state else "", t.to_state.value) for t in live_result.transitions
    ]
