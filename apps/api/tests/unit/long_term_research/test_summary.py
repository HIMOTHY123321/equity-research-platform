"""AI text cannot change deterministic state -- app.long_term_research.
summary.render_plain_english_summary is a pure string-rendering function
with no return path into `research_state` whatsoever (v1 doesn't call
any language model at all; see that module's own docstring for why)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.long_term_research.schemas import (
    BusinessQualityState,
    EarningsTrendState,
    GrowthState,
    LongTermEvidenceQuality,
    LongTermFactorBundle,
    LongTermFactorEvidence,
    LongTermResearchResult,
    LongTermResearchState,
    LongTermTrendState,
    ValuationState,
)
from app.long_term_research.summary import render_plain_english_summary

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _result(state: LongTermResearchState) -> LongTermResearchResult:
    empty = LongTermFactorEvidence()
    factors = LongTermFactorBundle(
        business_quality=BusinessQualityState.STRONG,
        business_quality_evidence=empty,
        earnings_trend=EarningsTrendState.IMPROVING,
        earnings_trend_evidence=empty,
        valuation=ValuationState.CHEAP,
        valuation_evidence=empty,
        growth=GrowthState.STRONG,
        growth_evidence=empty,
        long_term_trend=LongTermTrendState.CONSTRUCTIVE,
        long_term_trend_evidence=empty,
        history_days=500,
        limited_history=False,
    )
    return LongTermResearchResult(
        symbol="AAPL",
        as_of=AS_OF,
        price=150.0,
        research_state=state,
        factors=factors,
        evidence_quality=LongTermEvidenceQuality.STRONG,
        positive_evidence=["Strong business quality."],
        negative_evidence=[],
        contradictions=[],
        missing_evidence=[],
        reason="A majority of long-term factors are favorable.",
        what_would_change_state="Valuation becoming expensive.",
        market_data_provider="fixture",
        fundamentals_provider="fixture",
    )


def test_render_plain_english_summary_returns_a_string_not_a_result():
    result = _result(LongTermResearchState.ACCUMULATION_CANDIDATE)
    summary = render_plain_english_summary(result)
    assert isinstance(summary, str)
    assert summary


def test_rendering_the_summary_never_changes_research_state():
    result = _result(LongTermResearchState.ACCUMULATION_CANDIDATE)
    before = result.research_state
    render_plain_english_summary(result)
    assert result.research_state == before  # pydantic model unmutated by the call


def test_summary_function_signature_has_no_path_back_into_research_state():
    """Structural proof: the function returns `str`, never a
    LongTermResearchResult or anything else that could carry a
    research_state value back into the pipeline."""
    import inspect

    signature = inspect.signature(render_plain_english_summary)
    assert signature.return_annotation == "str"


def test_summary_reflects_only_already_decided_fields():
    """The summary text is built purely from fields already fixed on
    the result (reason/evidence/what_would_change) -- changing
    research_state alone (with the same reason/evidence) does not
    change the rendered text, proving the renderer never re-derives or
    second-guesses the state."""
    accumulation = _result(LongTermResearchState.ACCUMULATION_CANDIDATE)
    thesis_invalidated_same_reasons = accumulation.model_copy(
        update={"research_state": LongTermResearchState.THESIS_INVALIDATED}
    )
    assert render_plain_english_summary(accumulation) == render_plain_english_summary(
        thesis_invalidated_same_reasons
    )
