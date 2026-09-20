"""Phase 12 (#H/#I/#O/#P): baselines, performance metrics, and the Forward
Validation Gate are all pure functions over plain lists of ForwardForecast/
ForecastOutcome -- tested here against directly-constructed synthetic
records (no pipeline needed), same as app.forecasting.gate's own docstring
describes the gate as "a separate gate from the RANKING GATE."
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.forecasting.baselines import compute_baselines
from app.forecasting.gate import GATE_V1_CRITERIA, GateCriteria, GateDecision, evaluate_gate
from app.forecasting.metrics import compute_performance, overall_performance
from app.forecasting.schemas import (
    AbstentionReason,
    EvidenceQualityState,
    ForecastCategory,
    ForecastOrigin,
    ForecastOutcome,
    ForecastOutcomeCategory,
    ForecastRunMode,
    ForecastStatus,
    ForwardForecast,
)

_BASE = datetime(2026, 1, 5, 15, 0, 0, tzinfo=timezone.utc)


def _forecast(
    idx: int,
    symbol: str = "SPY",
    category: ForecastCategory = ForecastCategory.DIRECTION,
    value: str | None = "up",
    status: ForecastStatus = ForecastStatus.ACTIVE,
    abstention_reason: AbstentionReason | None = None,
    run_mode: ForecastRunMode = ForecastRunMode.PROSPECTIVE,
    weeks_offset: int = 0,
) -> ForwardForecast:
    market_as_of = _BASE + timedelta(weeks=weeks_offset, hours=idx)
    return ForwardForecast(
        forecast_id=f"forecast-{idx}",
        created_at=market_as_of,
        market_as_of=market_as_of,
        symbol=symbol,
        timeframe="1h",
        forecast_category=category,
        forecast_value=value,
        forecast_horizon_bars=5,
        evidence_packet_id=f"packet-{idx}",
        evidence_packet_schema_version="1.0",
        pipeline_version="1.0",
        evidence_quality=EvidenceQualityState.MIXED_EVIDENCE,
        origin=ForecastOrigin.DETERMINISTIC_RESEARCH,
        status=status,
        abstention_reason=abstention_reason,
        run_mode=run_mode,
    )


def _outcome(
    forecast: ForwardForecast, outcome: ForecastOutcomeCategory, actual_value: str | None
) -> ForecastOutcome:
    return ForecastOutcome(
        outcome_id=f"outcome-{forecast.forecast_id}",
        forecast_id=forecast.forecast_id,
        resolved_at=forecast.market_as_of + timedelta(hours=5),
        resolution_as_of=forecast.market_as_of + timedelta(hours=5),
        outcome=outcome,
        actual_value=actual_value,
    )


# ------------------------------------------------------------------ metrics


def test_compute_performance_counts_and_rates():
    forecasts = [
        _forecast(1, value="up", status=ForecastStatus.ACTIVE),
        _forecast(2, value="down", status=ForecastStatus.ACTIVE),
        _forecast(
            3, value=None, status=ForecastStatus.ABSTAINED, abstention_reason=AbstentionReason.STALE_DATA
        ),
    ]
    outcomes = {
        "forecast-1": _outcome(forecasts[0], ForecastOutcomeCategory.CORRECT, "up"),
        "forecast-2": _outcome(forecasts[1], ForecastOutcomeCategory.INCORRECT, "up"),
    }
    breakdown = overall_performance(forecasts, outcomes)
    assert breakdown.forecast_count == 3
    assert breakdown.resolved_count == 2
    assert breakdown.abstained_count == 1
    assert breakdown.correct_count == 1
    assert breakdown.incorrect_count == 1
    assert breakdown.directional_accuracy == 0.5
    assert breakdown.coverage_rate == 2 / 3
    assert breakdown.abstention_rate == 1 / 3


def test_compute_performance_groups_by_the_given_key():
    forecasts = [_forecast(1, symbol="SPY"), _forecast(2, symbol="AAPL")]
    groups = compute_performance(forecasts, {}, group_key=lambda f: f.symbol)
    assert {g.group for g in groups} == {"SPY", "AAPL"}


def test_overall_performance_with_no_forecasts_at_all_does_not_crash():
    breakdown = overall_performance([], {})
    assert breakdown.forecast_count == 0
    assert breakdown.directional_accuracy is None


def test_unresolved_active_forecast_has_no_accuracy_yet():
    forecasts = [_forecast(1, value="up", status=ForecastStatus.ACTIVE)]
    breakdown = overall_performance(forecasts, {})
    assert breakdown.resolved_count == 0
    assert breakdown.directional_accuracy is None


# ---------------------------------------------------------------- baselines


def test_always_up_baseline_reflects_actual_up_rate():
    forecasts = [_forecast(i, category=ForecastCategory.DIRECTION, value="up") for i in range(4)]
    outcomes = {
        f.forecast_id: _outcome(f, ForecastOutcomeCategory.CORRECT, actual)
        for f, actual in zip(forecasts, ["up", "up", "down", "flat_indeterminate"])
    }
    baselines = {b.name: b for b in compute_baselines(forecasts, outcomes)}
    assert baselines["always_up"].accuracy == 0.5
    assert baselines["always_up"].sample_size == 4


def test_baselines_with_no_resolved_pairs_are_none_not_zero():
    forecasts = [_forecast(1, value="up")]
    baselines = {b.name: b for b in compute_baselines(forecasts, {})}
    assert baselines["always_up"].accuracy is None
    assert baselines["always_up"].sample_size == 0


def test_same_symbol_baseline_uses_majority_actual_per_symbol():
    forecasts = [_forecast(i, symbol="SPY", value="up") for i in range(3)]
    outcomes = {
        f.forecast_id: _outcome(f, ForecastOutcomeCategory.CORRECT, actual)
        for f, actual in zip(forecasts, ["up", "up", "down"])
    }
    baselines = {b.name: b for b in compute_baselines(forecasts, outcomes)}
    # Majority actual for SPY is "up" (2 of 3) -> baseline "always guess up" scores 2/3.
    assert round(baselines["same_symbol_historical"].accuracy, 4) == round(2 / 3, 4)


# -------------------------------------------------------------------- gate


def _prospective_pool(count: int, weeks: int, symbols=("SPY",)) -> tuple[list[ForwardForecast], dict]:
    forecasts = []
    outcomes = {}
    for i in range(count):
        symbol = symbols[i % len(symbols)]
        week = i % weeks
        forecast = _forecast(i, symbol=symbol, value="up", weeks_offset=week)
        forecasts.append(forecast)
        actual = "up" if i % 2 == 0 else "down"
        outcomes[forecast.forecast_id] = _outcome(
            forecast,
            ForecastOutcomeCategory.CORRECT if actual == "up" else ForecastOutcomeCategory.INCORRECT,
            actual,
        )
    return forecasts, outcomes


def test_gate_is_not_enough_data_below_thresholds():
    forecasts, outcomes = _prospective_pool(5, weeks=3)
    evaluation = evaluate_gate(forecasts, outcomes)
    assert evaluation.decision == GateDecision.NOT_ENOUGH_DATA


def test_gate_excludes_backtest_replay_forecasts_from_evaluation():
    forecasts, outcomes = _prospective_pool(5, weeks=3)
    backtest_forecasts = [
        _forecast(100 + i, run_mode=ForecastRunMode.BACKTEST_REPLAY, weeks_offset=i) for i in range(40)
    ]
    evaluation_without_backtest = evaluate_gate(forecasts, outcomes)
    evaluation_with_backtest = evaluate_gate(forecasts + backtest_forecasts, outcomes)
    assert evaluation_without_backtest.forecast_count == evaluation_with_backtest.forecast_count


def test_gate_fails_on_excessive_single_symbol_concentration():
    criteria = GateCriteria(
        min_prospective_forecast_count=10,
        min_independent_resolved_episodes=5,
        max_single_symbol_share=0.5,
    )
    forecasts, outcomes = _prospective_pool(20, weeks=10, symbols=("SPY",))
    evaluation = evaluate_gate(forecasts, outcomes, criteria=criteria)
    assert evaluation.decision == GateDecision.FAIL
    assert any("symbol" in reason.lower() for reason in evaluation.reasons)


def test_gate_passes_when_accuracy_clears_baseline_by_the_required_margin():
    criteria = GateCriteria(
        min_prospective_forecast_count=10,
        min_independent_resolved_episodes=5,
        max_single_symbol_share=1.0,
        max_single_time_bucket_share=1.0,
        min_accuracy_margin_over_baseline_pp=5.0,
    )
    forecasts = []
    outcomes = {}
    symbols = ["SPY", "AAPL", "MSFT", "TSLA"]
    for i in range(20):
        # Actual outcome follows a period-5 pattern against a period-4
        # symbol cycle (coprime periods -> every symbol group sees a mixed
        # 3-up/2-down split, so no baseline -- always-up, same-symbol,
        # matched-unconditional -- can exceed 60%). The forecast's own
        # value always matches the actual, so the real system is 100%
        # correct: a genuine, non-trivial margin over every baseline.
        actual = "up" if i % 5 < 3 else "down"
        forecast = _forecast(i, symbol=symbols[i % len(symbols)], value=actual, weeks_offset=i)
        forecasts.append(forecast)
        outcomes[forecast.forecast_id] = _outcome(forecast, ForecastOutcomeCategory.CORRECT, actual)
    evaluation = evaluate_gate(forecasts, outcomes, criteria=criteria)
    assert evaluation.decision == GateDecision.PASS
    assert evaluation.accuracy == 1.0


def test_default_gate_version_is_v1():
    assert GATE_V1_CRITERIA.min_prospective_forecast_count == 30
