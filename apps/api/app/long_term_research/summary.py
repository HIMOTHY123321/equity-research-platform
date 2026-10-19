"""The "AI may summarize deterministic evidence in plain English but may
NOT choose or override the research state" surface, per spec.

v1 deliberately does NOT call any language model. `render_plain_english_summary`
is a pure deterministic template over an already-fully-decided
LongTermResearchResult -- it reads `result.research_state` (set entirely
by app.long_term_research.rules, before this function is ever called) and
returns a string; it has no return path that could feed back into
`research_state`, and no caller anywhere passes its output back into the
rules engine. This is the safest possible interpretation of "AI may
summarize... may NOT override": with no model in the loop at all, there
is no hallucination/override risk to mitigate in the first place. See the
final Phase report for why this scope decision was made, and
app.ai_analysis for the grounding/validation machinery that WOULD be
reused if/when an LLM-backed version is added later.
"""

from __future__ import annotations

from app.long_term_research.schemas import LongTermResearchResult


def render_plain_english_summary(result: LongTermResearchResult) -> str:
    lines = [result.reason]
    if result.positive_evidence:
        lines.append("For: " + " ".join(result.positive_evidence))
    if result.negative_evidence:
        lines.append("Against: " + " ".join(result.negative_evidence))
    if result.contradictions:
        lines.append(" ".join(result.contradictions))
    if result.missing_evidence:
        lines.append("Missing: " + ", ".join(result.missing_evidence) + ".")
    lines.append(f"What would change this: {result.what_would_change_state}")
    return " ".join(lines)
