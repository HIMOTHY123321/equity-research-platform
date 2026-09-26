"""Phase 15: the AI validation summary must be built ONLY from already-
frozen gate/cohort output, and must never contain BUY/SELL, recommendation,
or probability/confidence language."""

from __future__ import annotations

from datetime import datetime, timezone

from app.validation.ai_summary import (
    build_validation_summary,
    check_banned_language,
    generate_validation_summary_text,
)
from app.validation.gate import SignalGateDecision, SignalGateEvaluation
from app.validation.schemas import CohortStatistics

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _empty_cohort(event_type: str) -> CohortStatistics:
    return CohortStatistics(
        cohort_label=event_type,
        horizon_bars=5,
        raw_n=0,
        independent_n=0,
        purged_n=0,
        mean=None,
        median=None,
        stdev=None,
        p25=None,
        p75=None,
        positive_rate=None,
        mfe_atr_median=None,
        mae_atr_median=None,
        invalidation_rate=None,
        exit_rate=None,
        bootstrap_available=False,
        bootstrap_point_estimate=None,
        bootstrap_lower=None,
        bootstrap_upper=None,
        bootstrap_method=None,
        baseline_type=None,
        baseline_median=None,
        effect_vs_baseline=None,
        cost_sensitivity=[],
        concentration_warnings=[],
    )


def _not_enough_data_gate() -> SignalGateEvaluation:
    return SignalGateEvaluation(
        gate_version="v1",
        decision=SignalGateDecision.NOT_ENOUGH_DATA,
        reasons=[
            "0 independent episode(s) (need 20); 0 symbol(s) (need 5); 0.0 observation day(s) (need 20)."
        ],
        raw_n=0,
        independent_episode_count=0,
        symbol_count=0,
        observation_days=0.0,
    )


def test_summary_text_contains_no_banned_language_when_empty():
    gate = _not_enough_data_gate()
    cohorts = {et: _empty_cohort(et) for et in ("entry_conditions_met", "invalidated")}
    text = generate_validation_summary_text(gate, cohorts)
    assert check_banned_language(text) == []
    assert "NOT ENOUGH DATA" in text
    assert "not directive trading guidance" in text


def test_summary_text_reports_resolved_cohort_figures():
    gate = SignalGateEvaluation(
        gate_version="v1",
        decision=SignalGateDecision.PASS,
        raw_n=25,
        independent_episode_count=22,
        symbol_count=6,
        observation_days=25.0,
        median_effect=1.5,
    )
    entry = _empty_cohort("entry_conditions_met").model_copy(
        update={"raw_n": 25, "independent_n": 22, "median": 1.5, "positive_rate": 0.6}
    )
    cohorts = {"entry_conditions_met": entry}
    text = generate_validation_summary_text(gate, cohorts)
    assert check_banned_language(text) == []
    assert "25 raw observation" in text
    assert "1.50%" in text
    assert "60%" in text


def test_summary_never_contains_buy_sell_or_probability_language():
    gate = _not_enough_data_gate()
    cohorts = {et: _empty_cohort(et) for et in ("entry_conditions_met",)}
    text = generate_validation_summary_text(gate, cohorts)
    assert not check_banned_language(text)
    lowered = text.lower()
    assert "buy" not in lowered
    assert "sell" not in lowered
    assert "probability of" not in lowered
    assert "% confiden" not in lowered
    assert "guarantee" not in lowered


def test_build_validation_summary_falls_back_safely_if_banned_language_ever_slips_through(monkeypatch):
    import app.validation.ai_summary as ai_summary

    monkeypatch.setattr(
        ai_summary, "generate_validation_summary_text", lambda gate, cohorts: "you should buy now"
    )
    gate = _not_enough_data_gate()
    summary = ai_summary.build_validation_summary(gate, {}, now=_NOW)
    assert "buy" not in summary.text.lower()
    assert summary.text == ai_summary._SAFE_FALLBACK_TEXT


def test_build_validation_summary_round_trips_gate_metadata():
    gate = _not_enough_data_gate()
    summary = build_validation_summary(gate, {}, now=_NOW)
    assert summary.gate_version == "v1"
    assert summary.decision == "not_enough_data"
    assert summary.generated_at == _NOW
