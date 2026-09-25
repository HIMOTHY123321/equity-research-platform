from __future__ import annotations

from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
from app.decision_engine.scanner import build_scanner_rows
from app.decision_engine.schemas import DecisionState
from tests.unit.ai_analysis.conftest import make_session
from tests.unit.decision_engine.test_state_machine import make_plan


def _repo():
    return SqlAlchemyDecisionEngineRepository(make_session())


def test_symbol_with_no_plan_at_all_shows_state_none():
    repo = _repo()

    rows = build_scanner_rows(["AAPL"], repo)

    assert len(rows) == 1
    assert rows[0].symbol == "AAPL"
    assert rows[0].state is None
    assert rows[0].decision_plan_id is None


def test_symbol_whose_only_plan_abstained_shows_state_abstain_not_none():
    """Regression: an ABSTAIN-only symbol must never be indistinguishable
    from a symbol with no plan at all (§9)."""
    repo = _repo()
    plan = make_plan(DecisionState.ABSTAIN)
    repo.save_plan(plan)

    rows = build_scanner_rows(["AAPL"], repo)

    assert rows[0].symbol == "AAPL"
    assert rows[0].state == DecisionState.ABSTAIN
    assert rows[0].decision_plan_id == plan.decision_plan_id


def test_open_plan_takes_priority_over_a_separate_abstained_plan():
    repo = _repo()
    abstained = make_plan(DecisionState.ABSTAIN)
    watching = make_plan(DecisionState.WATCHING).model_copy(update={"decision_plan_id": "plan-2"})
    repo.save_plan(abstained)
    repo.save_plan(watching)

    rows = build_scanner_rows(["AAPL"], repo)

    assert rows[0].state == DecisionState.WATCHING
    assert rows[0].other_monitored_plan_count == 0  # the abstained plan doesn't count as "other monitored"


def test_invalidated_ranks_above_watching_above_abstain_above_no_plan():
    repo = _repo()
    invalidated = make_plan(DecisionState.INVALIDATED)
    watching = make_plan(DecisionState.WATCHING).model_copy(
        update={"decision_plan_id": "plan-2", "symbol": "NVDA"}
    )
    abstained = make_plan(DecisionState.ABSTAIN).model_copy(
        update={"decision_plan_id": "plan-3", "symbol": "MSFT"}
    )
    repo.save_plan(invalidated)
    repo.save_plan(watching)
    repo.save_plan(abstained)

    rows = build_scanner_rows(["AAPL", "NVDA", "MSFT", "TSLA"], repo)

    assert [r.symbol for r in rows] == ["AAPL", "NVDA", "MSFT", "TSLA"]
    assert rows[0].state == DecisionState.INVALIDATED
    assert rows[1].state == DecisionState.WATCHING
    assert rows[2].state == DecisionState.ABSTAIN
    assert rows[3].state is None


def test_never_exposes_a_ranking_score_field():
    rows = build_scanner_rows(["AAPL"], _repo())
    dumped = rows[0].model_dump()
    assert "score" not in dumped
    assert "rank" not in dumped
    assert "expected_return" not in dumped
