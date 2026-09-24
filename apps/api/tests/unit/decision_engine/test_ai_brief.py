from __future__ import annotations

from app.decision_engine.ai_brief import (
    build_decision_evidence_packet,
    contains_banned_language,
    what_would_change_state,
    why_not_yet,
    why_now,
)
from app.decision_engine.plan_builder import build_decision_plan
from tests.unit.decision_engine.conftest import spy_snapshot


def _watching_plan():
    snapshot = spy_snapshot()
    setup = next(
        s
        for s in snapshot.setup_snapshot.qualified_setups
        if len([c for c in s.soft_checks if c.passed]) >= 1
        and not any(c.severity.value == "major" for c in s.conflicts)
    )
    return build_decision_plan(setup, as_of=snapshot.as_of)


def test_why_not_yet_lists_missing_conditions_with_actual_and_required():
    plan = _watching_plan()
    packet = build_decision_evidence_packet(plan)

    text = why_not_yet(packet)

    assert "MISSING" in text
    for c in packet.missing_entry_conditions:
        assert c.description in text


def test_why_now_reports_not_reached_when_still_watching():
    plan = _watching_plan()
    packet = build_decision_evidence_packet(plan)

    text = why_now(packet)

    assert "has not reached" in text


def test_what_would_change_state_lists_entry_and_invalidation_paths_while_watching():
    plan = _watching_plan()
    packet = build_decision_evidence_packet(plan)

    lines = what_would_change_state(packet)

    assert any(line.startswith("ENTRY CONDITIONS MET if:") for line in lines)
    assert any(line.startswith("INVALIDATED if:") for line in lines)


def test_no_generated_text_contains_banned_language():
    plan = _watching_plan()
    packet = build_decision_evidence_packet(plan)

    texts = [why_not_yet(packet), why_now(packet), *what_would_change_state(packet)]
    for text in texts:
        assert contains_banned_language(text) == []


def test_contains_banned_language_detects_buy_sell_and_confidence():
    assert contains_banned_language("This is a strong BUY signal") == ["buy_sell_language"]
    assert contains_banned_language("85% confidence this will work") == ["confidence_percentage"]
    assert contains_banned_language("guaranteed win") == ["guaranteed_trade"]
    assert contains_banned_language("Entry conditions are not yet satisfied") == []
