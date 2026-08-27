from datetime import datetime, timezone

from app.research.replay import run_replay
from app.research_intelligence.concentration import detect_concentration
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _template_entry():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "concentration-test")
    return result.ledger_entries[0]


def _fake_entry(template, setup_id, symbol, timestamp):
    return template.model_copy(
        update={"setup_id": setup_id, "symbol": symbol, "candidate_candle_timestamp": timestamp}
    )


def test_symbol_concentration_hand_calculated():
    template = _template_entry()
    # 8 of 10 (80%) are NVDA -- above the default 50% threshold.
    entries = [
        _fake_entry(template, f"nvda{i}", "NVDA", datetime(2026, 1, i + 1, tzinfo=timezone.utc))
        for i in range(8)
    ] + [
        _fake_entry(template, f"spy{i}", "SPY", datetime(2026, 1, i + 1, tzinfo=timezone.utc))
        for i in range(2)
    ]
    report = detect_concentration(entries)
    symbol_warnings = [w for w in report.warnings if w.dimension == "symbol"]
    assert len(symbol_warnings) == 1
    assert symbol_warnings[0].dominant_value == "NVDA"
    assert abs(symbol_warnings[0].share - 0.8) < 1e-9
    assert "80%" in symbol_warnings[0].warning
    assert "NVDA" in symbol_warnings[0].warning


def test_no_warning_when_no_symbol_dominates():
    template = _template_entry()
    entries = [
        _fake_entry(template, f"e{i}", symbol, datetime(2026, 1, 1, tzinfo=timezone.utc))
        for i, symbol in enumerate(["SPY", "QQQ", "NVDA", "AAPL"])
    ]
    report = detect_concentration(entries)
    symbol_warnings = [w for w in report.warnings if w.dimension == "symbol"]
    assert symbol_warnings == []


def test_month_concentration_hand_calculated():
    template = _template_entry()
    entries = [
        _fake_entry(template, f"jan{i}", "SPY", datetime(2026, 1, i + 1, tzinfo=timezone.utc))
        for i in range(9)
    ] + [_fake_entry(template, "feb", "SPY", datetime(2026, 2, 1, tzinfo=timezone.utc))]
    report = detect_concentration(entries)
    month_warnings = [w for w in report.warnings if w.dimension == "month"]
    assert len(month_warnings) == 1
    assert month_warnings[0].dominant_value == "2026-01"
    assert abs(month_warnings[0].share - 0.9) < 1e-9


def test_empty_entries_produce_no_warnings():
    report = detect_concentration([])
    assert report.sample_count == 0
    assert report.warnings == []


def test_share_exactly_at_threshold_triggers_warning():
    template = _template_entry()
    entries = [
        _fake_entry(template, f"a{i}", "SPY", datetime(2026, 1, 1, tzinfo=timezone.utc)) for i in range(5)
    ] + [_fake_entry(template, f"b{i}", "QQQ", datetime(2026, 1, 1, tzinfo=timezone.utc)) for i in range(5)]
    # exactly 50% SPY -- the default threshold is 0.5, and the check is >=.
    report = detect_concentration(entries)
    symbol_warnings = [w for w in report.warnings if w.dimension == "symbol"]
    assert len(symbol_warnings) == 1
    assert abs(symbol_warnings[0].share - 0.5) < 1e-9


def test_real_data_does_not_crash_and_reports_sample_count():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "concentration-real")
    report = detect_concentration(result.ledger_entries)
    assert report.sample_count == len(result.ledger_entries)
    # Single-symbol replay -- every entry is the same symbol, so a symbol
    # concentration warning is expected (and correct) here.
    assert any(w.dimension == "symbol" for w in report.warnings)
