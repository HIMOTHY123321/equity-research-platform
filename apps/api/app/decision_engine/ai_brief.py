"""AI-facing explanation layer for a DecisionPlan (§25/§26/§27/§28 of the
Phase 13 spec).

The three trader-facing explanations required by the spec -- "WHY NOW?",
"WHY NOT YET?", "WHAT WOULD CHANGE THE STATE?" -- are deterministic,
template-built text over the DecisionPlan's own typed conditions, exactly
like app.setup_detection's `invalidation_criteria` (#30 there): no LLM call
is needed or used to produce them, so there is nothing for a provider to
hallucinate. This is a deliberate scope choice: the existing
AIAnalysisProvider ABC is shaped around EvidencePacket/EvidenceClaim (a
different domain object) and forcing DecisionPlan through it would mean
inventing new abstract methods with no other caller -- instead, an AI
provider may be handed the frozen DecisionEvidencePacket below to add
supplementary prose (`narrate_decision_state`), and that prose is passed
through the same banned-language filter every other AI surface in this
codebase uses, falling back to the deterministic text on any violation. No
code path here can change plan.state -- only state_machine.py can.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.decision_engine.schemas import (
    ConditionStatus,
    DecisionCondition,
    DecisionPlan,
    DecisionState,
    EvidenceDiffSnapshot,
)

# Same "no BUY/SELL/confidence/score language" convention as
# app.ai_analysis.validation._BANNED_PATTERNS, scoped to the terms Phase 13
# itself explicitly bans (§1 of the spec): BUY, SELL, guaranteed trade,
# confidence percentages, win probabilities, expected profit, arbitrary
# scores.
_BANNED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("buy_sell_language", re.compile(r"\b(strong\s+)?(buy|sell)\b", re.IGNORECASE)),
    ("guaranteed_trade", re.compile(r"\bguarantee[ds]?\b", re.IGNORECASE)),
    ("confidence_percentage", re.compile(r"\d+(?:\.\d+)?\s*%\s*confiden", re.IGNORECASE)),
    ("win_probability", re.compile(r"\bwin\s+probability\b|\d+(?:\.\d+)?\s*%\s*chance", re.IGNORECASE)),
    ("expected_profit", re.compile(r"\bexpected\s+profit\b", re.IGNORECASE)),
    ("arbitrary_score", re.compile(r"\b\d{1,3}\s*/\s*100\b|\bsetup\s+score\b", re.IGNORECASE)),
]


def contains_banned_language(text: str) -> list[str]:
    return [code for code, pattern in _BANNED_PATTERNS if pattern.search(text)]


class ConditionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    description: str
    status: ConditionStatus
    actual_value: Optional[float] = None
    required_value: Optional[float] = None


class DecisionEvidencePacket(BaseModel):
    """Frozen, deterministic evidence handed to an AI provider (§25) or
    rendered directly in the UI -- purely a re-presentation of the
    DecisionPlan's own already-computed facts, same convention as
    app.support_resistance.schemas.ZoneExplanation."""

    model_config = ConfigDict(frozen=True)

    decision_plan_id: str
    symbol: str
    timeframe: str
    setup_type: str
    direction: str
    state: DecisionState
    as_of: datetime

    satisfied_entry_conditions: list[ConditionSummary]
    missing_entry_conditions: list[ConditionSummary]
    active_invalidation_conditions: list[ConditionSummary]
    active_exit_conditions: list[ConditionSummary]
    conflicts: list[str]
    research_status: list[str]
    last_transition_reason: Optional[str] = None


def _summary(c: DecisionCondition) -> ConditionSummary:
    return ConditionSummary(
        id=c.id,
        description=c.description,
        status=c.status,
        actual_value=c.actual_value,
        required_value=c.required_value,
    )


def build_decision_evidence_packet(plan: DecisionPlan) -> DecisionEvidencePacket:
    satisfied = [c for c in plan.entry_conditions if c.status == ConditionStatus.PASSED]
    missing = [c for c in plan.entry_conditions if c.status != ConditionStatus.PASSED]
    return DecisionEvidencePacket(
        decision_plan_id=plan.decision_plan_id,
        symbol=plan.symbol,
        timeframe=plan.timeframe.value,
        setup_type=plan.setup_type.value,
        direction=plan.direction.value,
        state=plan.state,
        as_of=plan.as_of,
        satisfied_entry_conditions=[_summary(c) for c in satisfied],
        missing_entry_conditions=[_summary(c) for c in missing],
        active_invalidation_conditions=[_summary(c) for c in plan.invalidation_conditions],
        active_exit_conditions=[_summary(c) for c in plan.exit_conditions],
        conflicts=[],
        research_status=[s.value for s in plan.research_status],
        last_transition_reason=plan.transitions[-1].reason if plan.transitions else None,
    )


def why_not_yet(packet: DecisionEvidencePacket) -> str:
    """§28: "This is one of the most important trader-facing features" --
    explicit missing conditions with actual vs required values, never a
    vague "not a good entry yet."""
    if packet.state != DecisionState.WATCHING:
        return f"{packet.symbol} is not in WATCHING (current state: {packet.state.value})."
    if not packet.missing_entry_conditions:
        return (
            "All entry conditions are satisfied; awaiting the next evaluation to confirm "
            "ENTRY CONDITIONS MET."
        )
    lines = [
        f"Entry conditions are not yet satisfied for {packet.symbol} "
        f"({packet.setup_type}, {packet.direction})."
    ]
    for c in packet.missing_entry_conditions:
        actual = "unavailable" if c.actual_value is None else f"{c.actual_value:.2f}"
        required = "n/a" if c.required_value is None else f"{c.required_value:.2f}"
        lines.append(
            f"- MISSING: {c.description} (actual: {actual}, required: {required}, "
            f"status: {c.status.value})"
        )
    return "\n".join(lines)


_WHY_NOW_ELIGIBLE_STATES = (
    DecisionState.ENTRY_CONDITIONS_MET,
    DecisionState.ACTIVE_THESIS,
    DecisionState.THESIS_STRENGTHENING,
    DecisionState.THESIS_WEAKENING,
)


def why_now(packet: DecisionEvidencePacket) -> str:
    """Deterministic explanation of why ENTRY CONDITIONS MET occurred at
    this specific as_of, not earlier (§27)."""
    if packet.state not in _WHY_NOW_ELIGIBLE_STATES:
        return (
            f"{packet.symbol} has not reached ENTRY CONDITIONS MET " f"(current state: {packet.state.value})."
        )
    lines = [
        f"All predefined entry conditions for {packet.symbol} "
        f"({packet.setup_type}, {packet.direction}) are now satisfied "
        f"as of {packet.as_of.isoformat()}."
    ]
    for c in packet.satisfied_entry_conditions:
        actual = "unavailable" if c.actual_value is None else f"{c.actual_value:.2f}"
        lines.append(f"- SATISFIED: {c.description} (actual: {actual})")
    if packet.last_transition_reason:
        lines.append(f"Reason recorded at transition: {packet.last_transition_reason}")
    return "\n".join(lines)


def what_would_change_state(packet: DecisionEvidencePacket) -> list[str]:
    """§29: NEXT POSSIBLE STATE CHANGES -- the conditions that would trigger
    the plan's next legal transition(s), never a prediction of which one
    will happen."""
    lines: list[str] = []
    if packet.state == DecisionState.WATCHING:
        for c in packet.missing_entry_conditions:
            lines.append(f"ENTRY CONDITIONS MET if: {c.description}")
        for c in packet.active_invalidation_conditions:
            lines.append(f"INVALIDATED if: {c.description}")
    elif packet.state in (
        DecisionState.ACTIVE_THESIS,
        DecisionState.THESIS_STRENGTHENING,
        DecisionState.THESIS_WEAKENING,
    ):
        for c in packet.active_invalidation_conditions:
            lines.append(f"INVALIDATED if: {c.description}")
        for c in packet.active_exit_conditions:
            lines.append(f"EXIT CONDITIONS MET if: {c.description}")
    return lines


def explain_evidence_diff(diff: EvidenceDiffSnapshot) -> str:
    """Deterministic re-presentation of an EvidenceDiffSnapshot's own
    `classification_reasons` -- never independently re-interpreted."""
    if not diff.classification_reasons:
        return (
            f"Thesis classification: {diff.classification.value} "
            "(no qualifying evidence changes recorded)."
        )
    return f"Thesis classification: {diff.classification.value} -- " + "; ".join(diff.classification_reasons)
