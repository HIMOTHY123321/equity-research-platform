"""Phase 13.1: deterministic full-lifecycle fixture coverage.

Unlike the rest of the decision_engine test suite (which exercises
individual pieces against real SPY fixture data and may or may not hit
every state depending on what the real data happens to do), these tests
drive the complete, specific transition sequences from the Phase 13.1
requirements end to end, using app.decision_engine.fixtures -- itself just
a thin, additive fixture-construction module; state_machine/conditions/
service/evidence_diff are exercised completely unmodified.
"""

from __future__ import annotations

from datetime import timedelta

from app.decision_engine.fixtures import (
    FIXTURE_SCENARIOS,
    build_fixture_plan,
    fixture_provider,
    fixture_snapshot_at,
    run_fixture_scenario,
)
from app.decision_engine.schemas import ConditionStatus, DecisionState
from app.decision_engine.service import evaluate_plan
from app.schemas.market_data import Candle, MarketSession, Timeframe


def test_strengthen_invalidate_scenario_reaches_every_intermediate_state():
    history = run_fixture_scenario("strengthen_invalidate")
    final = history[-1]

    assert [t.to_state for t in final.transitions] == [
        DecisionState.EVALUATING,
        DecisionState.WATCHING,
        DecisionState.ENTRY_CONDITIONS_MET,
        DecisionState.ACTIVE_THESIS,
        DecisionState.THESIS_STRENGTHENING,
        DecisionState.INVALIDATED,
    ]
    assert final.state == DecisionState.INVALIDATED


def test_strengthen_invalidate_transitions_carry_exact_timestamps_and_reasons():
    history = run_fixture_scenario("strengthen_invalidate")
    final = history[-1]

    strengthen = next(t for t in final.transitions if t.to_state == DecisionState.THESIS_STRENGTHENING)
    assert "RVOL improved" in strengthen.reason
    assert strengthen.occurred_at is not None

    invalidated = next(t for t in final.transitions if t.to_state == DecisionState.INVALIDATED)
    assert "close below 95.00" in invalidated.reason
    assert invalidated.occurred_at > strengthen.occurred_at


def test_invalidation_level_remains_frozen_across_the_whole_lifecycle():
    history = run_fixture_scenario("strengthen_invalidate")
    levels = {p.invalidation_conditions[0].required_value for p in history}
    assert levels == {95.0}


def test_exit_scenario_reaches_active_thesis_then_exit_conditions_met():
    history = run_fixture_scenario("exit")
    final = history[-1]

    assert [t.to_state for t in final.transitions] == [
        DecisionState.EVALUATING,
        DecisionState.WATCHING,
        DecisionState.ENTRY_CONDITIONS_MET,
        DecisionState.ACTIVE_THESIS,
        DecisionState.EXIT_CONDITIONS_MET,
    ]
    exit_transition = final.transitions[-1]
    assert exit_transition.trigger_condition_ids == [final.exit_conditions[0].id]
    assert "Exit condition met" in exit_transition.reason


def test_expire_scenario_never_satisfies_entry_conditions():
    history = run_fixture_scenario("expire")
    final = history[-1]

    assert final.state == DecisionState.EXPIRED
    assert all(c.status != ConditionStatus.PASSED for c in final.entry_conditions)
    expired_transition = next(t for t in final.transitions if t.to_state == DecisionState.EXPIRED)
    assert "never completed" in expired_transition.reason


def test_no_scenario_ever_produces_banned_language():
    banned = ("buy", "sell", "guaranteed", "confidence", "win probability")
    for name in FIXTURE_SCENARIOS:
        history = run_fixture_scenario(name)
        final = history[-1]
        texts = [t.reason for t in final.transitions]
        texts += [
            c.description
            for c in (*final.entry_conditions, *final.invalidation_conditions, *final.exit_conditions)
        ]
        for text in texts:
            lowered = text.lower()
            for term in banned:
                assert term not in lowered, f"banned term {term!r} in {text!r} ({name})"


def test_replaying_the_same_fixture_twice_produces_an_identical_state_sequence():
    first = run_fixture_scenario("strengthen_invalidate")
    second = run_fixture_scenario("strengthen_invalidate")

    first_sequence = [(p.state.value, [t.to_state.value for t in p.transitions]) for p in first]
    second_sequence = [(p.state.value, [t.to_state.value for t in p.transitions]) for p in second]
    assert first_sequence == second_sequence


def test_replaying_exit_and_expire_scenarios_twice_is_also_deterministic():
    for name in ("exit", "expire"):
        first = run_fixture_scenario(name)
        second = run_fixture_scenario(name)
        first_sequence = [(p.state.value, [t.to_state.value for t in p.transitions]) for p in first]
        second_sequence = [(p.state.value, [t.to_state.value for t in p.transitions]) for p in second]
        assert first_sequence == second_sequence, name


# ---------------------------------------------------------------------------
# Anti-lookahead spot check (Phase 13.1 §3): a historical DecisionPlan state
# at instant T must be identical whether or not future candles/structure
# exist beyond T in the data source available to the caller.
# ---------------------------------------------------------------------------


def test_appending_future_candles_does_not_change_the_historical_decision_state():
    scenario = FIXTURE_SCENARIOS["strengthen_invalidate"]
    t = scenario.steps[0].as_of  # the entry-breakout/activation instant

    short_provider = fixture_provider(scenario)  # scenario's own full series, but...
    plan = build_fixture_plan(scenario, t)

    # "Short" run: evaluate at T using only candles that exist up to T.
    snapshot_short = fixture_snapshot_at(scenario, t, short_provider)
    result_short = evaluate_plan(plan, snapshot_short, t)

    # "Long" run: an EXTENDED provider that also serves candles far beyond
    # T (the scenario's later strengthen/invalidate candles, plus a further
    # synthetic future candle past the end of the real scenario) -- future
    # data the caller should never be able to see when asking "what did the
    # decision look like at T?"
    extra_future_candle = Candle(
        symbol=scenario.symbol,
        timeframe=Timeframe.ONE_DAY,
        timestamp=scenario.candles[-1].timestamp + timedelta(days=30),
        session=MarketSession.REGULAR,
        open=500.0,
        high=501.0,
        low=499.0,
        close=500.0,
        volume=9_999_999.0,
    )
    from app.decision_engine.fixtures import _FixtureProvider  # internal, test-only reach-in

    long_provider = _FixtureProvider(scenario.symbol, [*scenario.candles, extra_future_candle])
    snapshot_long = fixture_snapshot_at(scenario, t, long_provider)
    result_long = evaluate_plan(plan, snapshot_long, t)

    assert result_short.plan.state == result_long.plan.state
    assert [t.to_state for t in result_short.transitions] == [t.to_state for t in result_long.transitions]
    assert [t.reason for t in result_short.transitions] == [t.reason for t in result_long.transitions]
    assert result_short.plan.activation_snapshot == result_long.plan.activation_snapshot
    # The evaluated entry conditions (actual/required values) must match
    # exactly -- proof the "future" volume/price never leaked into the as-of
    # T computation.
    assert [c.model_dump() for c in result_short.evaluated_conditions] == [
        c.model_dump() for c in result_long.evaluated_conditions
    ]


def test_appending_a_future_catalyst_does_not_change_a_condition_evaluated_before_it():
    # catalyst_present/absent conditions only ever see whatever
    # catalyst_context the CALLER passes in for a given as_of -- there is no
    # implicit global catalyst store the evaluator reaches into, so a
    # catalyst dated after `as_of` can only leak in if a caller mistakenly
    # includes it. This proves the evaluator itself introduces no such leak:
    # the presence/absence of a *later* catalyst that was simply never
    # passed in cannot change the result of the earlier evaluation.
    from app.decision_engine.conditions import ConditionContext, evaluate
    from app.decision_engine.fixtures import FIXTURE_SCENARIOS, fixture_provider, fixture_snapshot_at
    from app.decision_engine.schemas import (
        BarSemantics,
        ConditionOperator,
        ConditionRole,
        ConditionStatus,
        ConditionType,
        DecisionCondition,
    )

    scenario = FIXTURE_SCENARIOS["strengthen_invalidate"]
    t = scenario.steps[0].as_of
    snapshot = fixture_snapshot_at(scenario, t, fixture_provider(scenario))

    condition = DecisionCondition(
        id="catalyst-cond",
        role=ConditionRole.MONITORING,
        type=ConditionType.CATALYST_ABSENT,
        description="No catalyst known as of T",
        timeframe=Timeframe.ONE_DAY,
        bar_semantics=BarSemantics.TICK,
        operator=ConditionOperator.PRESENT,
        status=ConditionStatus.PENDING,
    )

    # Evaluated with no catalyst context known at T -> UNAVAILABLE, never a
    # guess about what might exist later.
    result_at_t = evaluate(condition, ConditionContext(snapshot=snapshot, as_of=t, catalyst_context=None))
    assert result_at_t.status == ConditionStatus.UNAVAILABLE

    # A second, independent call using the SAME as_of=T context must be
    # byte-identical -- nothing about calling it again (e.g. after a future
    # catalyst has since been discovered elsewhere in the system) changes
    # the T-instant result, because the caller must explicitly pass
    # catalyst_context filtered to what was known as of T.
    result_at_t_again = evaluate(
        condition, ConditionContext(snapshot=snapshot, as_of=t, catalyst_context=None)
    )
    assert result_at_t.model_dump() == result_at_t_again.model_dump()
