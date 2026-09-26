"""Phase 15: the AI validation summary -- a short, deterministic-only
prose recap of the Signal Validation Gate + per-event-type cohort
statistics already computed by app.validation.{gate,cohort}. This module
never calls an external AI provider: it is a pure, template-based text
generator over already-frozen numbers, mirroring the same "never invent,
never predict" discipline app.ai_analysis.validation enforces for
EvidencePacket-grounded briefs, but reimplemented standalone here because
there is no EvidencePacket/EvidenceClaim in this domain to ground against
-- the deterministic gate/cohort output IS the grounding.

Never emits BUY/SELL, a recommendation, or a probability/confidence claim
-- `_BANNED_PATTERNS` is checked against the generated text as a defense-
in-depth safety net even though the generator's own templates cannot
produce any of these by construction."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from app.validation.gate import SignalGateEvaluation
from app.validation.schemas import CohortStatistics

VALIDATION_SUMMARY_SCHEMA_VERSION = "1.0"

_EVENT_TYPE_LABELS: dict[str, str] = {
    "entry_conditions_met": "Entry conditions",
    "thesis_strengthening": "Strengthening",
    "thesis_weakening": "Weakening",
    "invalidated": "Invalidation",
    "exit_conditions_met": "Exit",
}

_BANNED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("buy_recommendation", re.compile(r"\b(strong\s+)?buy\b", re.IGNORECASE)),
    ("sell_recommendation", re.compile(r"\b(strong\s+)?sell\b", re.IGNORECASE)),
    ("recommendation_language", re.compile(r"\brecommend(?:ed|s|ation)?\b", re.IGNORECASE)),
    ("probability_claim", re.compile(r"\d+(?:\.\d+)?\s*%\s*chance", re.IGNORECASE)),
    ("probability_claim_alt", re.compile(r"\bprobability\s+of\b", re.IGNORECASE)),
    ("confidence_claim", re.compile(r"\d+(?:\.\d+)?\s*%\s*confiden", re.IGNORECASE)),
    ("certainty_claim", re.compile(r"\bguarantee[ds]?\b", re.IGNORECASE)),
    ("will_language", re.compile(r"\bwill\s+(rise|fall|go|move|increase|decrease)\b", re.IGNORECASE)),
    ("expect_language", re.compile(r"\bexpect(?:ed|s)?\s+to\b", re.IGNORECASE)),
]

_SAFE_FALLBACK_TEXT = (
    "A validation summary could not be safely generated for this data. "
    "See the gate and cohort panels above for the underlying deterministic figures."
)


class ValidationSummary(BaseModel):
    """Immutable output of one summary-generation pass -- never persisted
    as a standing recommendation, always regenerable from the same
    already-frozen gate/cohort inputs (§ AI validation summary)."""

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    gate_version: str
    decision: str
    text: str
    schema_version: str = VALIDATION_SUMMARY_SCHEMA_VERSION


def check_banned_language(text: str) -> list[str]:
    return [code for code, pattern in _BANNED_PATTERNS if pattern.search(text)]


def _cohort_sentence(event_type: str, stats: CohortStatistics) -> str:
    label = _EVENT_TYPE_LABELS.get(event_type, event_type.replace("_", " "))
    if stats.raw_n == 0:
        return f"{label}: not enough data yet (0 observations)."
    median = f"{stats.median:.2f}%" if stats.median is not None else "unavailable"
    positive_rate = f"{stats.positive_rate * 100:.0f}%" if stats.positive_rate is not None else "unavailable"
    sentence = (
        f"{label}: {stats.raw_n} raw observation(s), {stats.independent_n} independent episode(s), "
        f"median {stats.horizon_bars}-bar return {median}, positive-return rate {positive_rate}."
    )
    if stats.concentration_warnings:
        dims = ", ".join(w.dimension for w in stats.concentration_warnings)
        sentence += f" Concentration warning(s) present ({dims})."
    return sentence


def generate_validation_summary_text(
    gate: SignalGateEvaluation, cohorts: dict[str, CohortStatistics]
) -> str:
    """Assembles plain, descriptive sentences purely from already-computed
    gate/cohort fields -- no field is ever interpolated through a
    free-text template that could accidentally introduce banned language,
    and no number here is anything other than a direct read of an
    existing dataclass/model attribute."""
    lines: list[str] = []

    gate_days = f"{gate.observation_days:.1f}" if gate.observation_days is not None else "0.0"
    lines.append(
        f"Forward Validation Gate: {gate.decision.value.replace('_', ' ').upper()} "
        f"(gate version {gate.gate_version}). "
        f"{gate.raw_n} resolved observation(s) across {gate.independent_episode_count} independent "
        f"episode(s) and {gate.symbol_count} symbol(s) over {gate_days} observation day(s)."
    )
    if gate.reasons:
        lines.append("Reasons: " + " ".join(gate.reasons))

    for event_type, stats in cohorts.items():
        lines.append(_cohort_sentence(event_type, stats))

    lines.append(
        "This is a descriptive research summary of past observations only -- it is not directive trading "
        "guidance and contains no probability or confidence estimate of future performance."
    )
    return " ".join(lines)


def build_validation_summary(
    gate: SignalGateEvaluation, cohorts: dict[str, CohortStatistics], *, now: datetime | None = None
) -> ValidationSummary:
    generated_at = now or datetime.now(timezone.utc)
    text = generate_validation_summary_text(gate, cohorts)
    if check_banned_language(text):
        # Defense in depth only -- the template above cannot produce any
        # banned pattern, so reaching this branch would indicate a
        # generator bug, not bad input data. Never serve unsanitized text.
        text = _SAFE_FALLBACK_TEXT
    return ValidationSummary(
        generated_at=generated_at,
        gate_version=gate.gate_version,
        decision=gate.decision.value,
        text=text,
    )
