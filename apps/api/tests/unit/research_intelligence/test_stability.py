from datetime import datetime, timezone

from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.outcomes import evaluate_setup_outcome
from app.research.replay import run_replay
from app.research.schemas import EvaluationQuality, ExcursionMetrics, HorizonOutcome, SetupOutcome
from app.research_intelligence.schemas import StabilityLabel
from app.research_intelligence.stability import bucket_label, cross_symbol_stability, temporal_stability
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _template_entry():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "stability-test")
    return result.ledger_entries[0]


def _fake_entry(template, setup_id, symbol, timestamp, directional_return, horizon_bars=5):
    outcome = SetupOutcome(
        setup_id=setup_id,
        base_price=100.0,
        evaluation_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        horizons=[
            HorizonOutcome(
                horizon_bars=horizon_bars, available=True, directional_return_percent=directional_return
            )
        ],
        mfe=ExcursionMetrics(atr=1.0),
        mae=ExcursionMetrics(atr=-1.0),
        evaluation_quality=EvaluationQuality(
            bars_available_after_detection=horizon_bars, fully_evaluated=True
        ),
    )
    return template.model_copy(
        update={
            "setup_id": setup_id,
            "symbol": symbol,
            "candidate_candle_timestamp": timestamp,
            "outcome": outcome,
        }
    )


def test_bucket_label_monthly_and_quarterly():
    template = _template_entry()
    jan = _fake_entry(template, "e1", "SPY", datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc), 0.5)
    assert bucket_label(jan, "monthly") == "2026-01"
    assert bucket_label(jan, "quarterly") == "2026-Q1"

    aug = _fake_entry(template, "e2", "SPY", datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc), 0.5)
    assert bucket_label(aug, "monthly") == "2026-08"
    assert bucket_label(aug, "quarterly") == "2026-Q3"


def test_temporal_stability_detects_a_sign_flip_across_months():
    template = _template_entry()
    entries = [
        _fake_entry(template, "e1", "SPY", datetime(2026, 1, 15, tzinfo=timezone.utc), 0.5),
        _fake_entry(template, "e2", "SPY", datetime(2026, 1, 16, tzinfo=timezone.utc), 0.4),
        _fake_entry(template, "e3", "SPY", datetime(2026, 2, 15, tzinfo=timezone.utc), -0.3),
        _fake_entry(template, "e4", "SPY", datetime(2026, 2, 16, tzinfo=timezone.utc), -0.6),
    ]
    report = temporal_stability(entries, horizon_bars=5, granularity="monthly")
    assert [b.bucket_label for b in report.buckets] == ["2026-01", "2026-02"]
    assert report.stability == StabilityLabel.UNSTABLE
    assert "sign" in report.stability_basis


def test_temporal_stability_stable_when_sign_is_consistent():
    template = _template_entry()
    entries = [
        _fake_entry(template, "e1", "SPY", datetime(2026, 1, 15, tzinfo=timezone.utc), 0.5),
        _fake_entry(template, "e2", "SPY", datetime(2026, 2, 15, tzinfo=timezone.utc), 0.3),
        _fake_entry(template, "e3", "SPY", datetime(2026, 3, 15, tzinfo=timezone.utc), 0.2),
    ]
    report = temporal_stability(entries, horizon_bars=5, granularity="monthly")
    assert report.stability == StabilityLabel.STABLE


def test_temporal_stability_insufficient_data_with_one_bucket():
    template = _template_entry()
    entries = [_fake_entry(template, "e1", "SPY", datetime(2026, 1, 15, tzinfo=timezone.utc), 0.5)]
    report = temporal_stability(entries, horizon_bars=5, granularity="monthly")
    assert report.stability == StabilityLabel.INSUFFICIENT_DATA


def test_cross_symbol_stability_hand_calculated_counts():
    template = _template_entry()
    entries = [
        _fake_entry(template, "e1", "SPY", datetime(2026, 1, 1, tzinfo=timezone.utc), 0.5),
        _fake_entry(template, "e2", "SPY", datetime(2026, 1, 2, tzinfo=timezone.utc), 0.6),
        _fake_entry(template, "e3", "QQQ", datetime(2026, 1, 1, tzinfo=timezone.utc), -0.2),
        _fake_entry(template, "e4", "NVDA", datetime(2026, 1, 1, tzinfo=timezone.utc), 0.1),
    ]
    report = cross_symbol_stability(entries, horizon_bars=5)
    assert report.symbols_with_data == 3
    assert report.symbols_positive_median == 2  # SPY, NVDA
    assert report.symbols_negative_median == 1  # QQQ
    symbols = {s.symbol for s in report.per_symbol}
    assert symbols == {"SPY", "QQQ", "NVDA"}


def test_cross_symbol_stability_never_drops_a_symbol():
    template = _template_entry()
    entries = [
        _fake_entry(template, f"e{i}", symbol, datetime(2026, 1, 1, tzinfo=timezone.utc), 0.1)
        for i, symbol in enumerate(["SPY", "QQQ", "NVDA", "AAPL", "MSFT"])
    ]
    report = cross_symbol_stability(entries, horizon_bars=5)
    assert len(report.per_symbol) == 5


def test_real_data_temporal_and_cross_symbol_stability_do_not_crash():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "stability-real")
    entries = []
    for e in result.ledger_entries:
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)

    temporal = temporal_stability(entries, horizon_bars=5)
    cross_symbol = cross_symbol_stability(entries, horizon_bars=5)
    assert temporal.stability in StabilityLabel
    assert cross_symbol.pooled.n == sum(s.distribution.n for s in cross_symbol.per_symbol)
