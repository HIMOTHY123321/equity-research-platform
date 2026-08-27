from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.outcomes import evaluate_setup_outcome
from app.research.replay import run_replay
from app.research_intelligence.qualification import (
    expanded_qualification_lift,
    independence_adjusted_qualification_lift,
)
from app.research_intelligence.rejection_value import (
    expanded_rejection_value,
    independence_adjusted_rejection_value,
    rejection_codes,
)
from app.research_intelligence.schemas import ConclusionLabel
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")
HORIZONS = (1, 3, 5, 10, 20)


def _real_entries_with_outcomes():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "qual-rej-test")
    entries = []
    for e in result.ledger_entries:
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)
    return entries


def test_expanded_qualification_lift_produces_one_result_per_horizon():
    entries = _real_entries_with_outcomes()
    trend_entries = [e for e in entries if e.setup_type == "trend_pullback"]
    qualified = [e for e in trend_entries if e.detection.current_state == "qualified"]
    rejected = [e for e in trend_entries if e.detection.current_state == "rejected"]

    results = expanded_qualification_lift(qualified, rejected, HORIZONS, seed=1)
    assert [r.horizon_bars for r in results] == list(HORIZONS)
    for r in results:
        assert r.group_a_label == "qualified"
        assert r.group_b_label == "rejected"


def test_rejection_codes_matches_the_phase_7_multi_bucket_convention():
    entries = _real_entries_with_outcomes()
    rejected = [e for e in entries if e.detection.current_state == "rejected"]
    by_code = rejection_codes(rejected)
    assert by_code  # at least one rejection code present in the real fixture

    # Every entry in a code's bucket really did fail that specific check.
    for code, code_entries in by_code.items():
        for entry in code_entries:
            failed_codes = {c.code for c in entry.detection.hard_checks if not c.passed}
            assert code in failed_codes


def test_an_entry_failing_multiple_hard_checks_appears_in_multiple_buckets():
    entries = _real_entries_with_outcomes()
    rejected = [e for e in entries if e.detection.current_state == "rejected"]
    multi_fail = next(
        (e for e in rejected if sum(1 for c in e.detection.hard_checks if not c.passed) > 1), None
    )
    if multi_fail is None:
        return  # no multi-failure entry in this real fixture window -- nothing to assert
    by_code = rejection_codes(rejected)
    codes_containing_entry = [code for code, es in by_code.items() if multi_fail in es]
    assert len(codes_containing_entry) > 1


def test_expanded_rejection_value_produces_one_result_per_code_per_horizon():
    entries = _real_entries_with_outcomes()
    trend_entries = [e for e in entries if e.setup_type == "trend_pullback"]
    qualified = [e for e in trend_entries if e.detection.current_state == "qualified"]
    rejected = [e for e in trend_entries if e.detection.current_state == "rejected"]

    by_code = expanded_rejection_value(rejected, qualified, HORIZONS, seed=2)
    assert by_code
    for code, results in by_code.items():
        assert [r.horizon_bars for r in results] == list(HORIZONS)
        for r in results:
            assert r.group_a_label == code
            assert r.group_b_label == "qualified"


def test_independence_adjusted_qualification_lift_produces_one_report_per_horizon():
    entries = _real_entries_with_outcomes()
    trend_entries = [e for e in entries if e.setup_type == "trend_pullback"]
    qualified = [e for e in trend_entries if e.detection.current_state == "qualified"]
    rejected = [e for e in trend_entries if e.detection.current_state == "rejected"]

    reports = independence_adjusted_qualification_lift(
        qualified, rejected, HORIZONS, timeframe=Timeframe.ONE_HOUR, seed=3
    )
    assert [r.horizon_bars for r in reports] == list(HORIZONS)
    for r in reports:
        assert r.finding_label == "qualification lift"
        assert r.label in list(ConclusionLabel)
        # <=, not ==: horizon_values only counts entries where that specific
        # horizon is `available` (enough future bars existed), which shrinks
        # for larger horizons near the end of the fixture window.
        assert r.raw.group_a_distribution.n <= len(qualified)
        assert r.raw.group_b_distribution.n <= len(rejected)
        assert r.purged.group_a_distribution.n <= r.raw.group_a_distribution.n
        assert r.episode.group_a_distribution.n <= r.raw.group_a_distribution.n


def test_independence_adjusted_rejection_value_produces_one_report_per_code_per_horizon():
    entries = _real_entries_with_outcomes()
    trend_entries = [e for e in entries if e.setup_type == "trend_pullback"]
    qualified = [e for e in trend_entries if e.detection.current_state == "qualified"]
    rejected = [e for e in trend_entries if e.detection.current_state == "rejected"]

    by_code = independence_adjusted_rejection_value(
        rejected, qualified, HORIZONS, timeframe=Timeframe.ONE_HOUR, seed=4
    )
    assert by_code
    for code, reports in by_code.items():
        assert [r.horizon_bars for r in reports] == list(HORIZONS)
        for r in reports:
            assert r.finding_label == f"rejection value: {code}"
            assert r.label in list(ConclusionLabel)
            assert r.purged.group_a_distribution.n <= r.raw.group_a_distribution.n
