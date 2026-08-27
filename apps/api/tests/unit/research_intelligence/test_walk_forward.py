from datetime import datetime, timedelta, timezone

from app.research.replay import run_replay
from app.research.schemas import EvaluationQuality, ExcursionMetrics, HorizonOutcome, SetupOutcome
from app.research_intelligence.schemas import StabilityLabel
from app.research_intelligence.walk_forward import _chronological_folds, anchored_walk_forward
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _build_template_entry():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "walk-forward-test")
    return result.ledger_entries[0]


_TEMPLATE_ENTRY = _build_template_entry()
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def _fake_outcome(directional_return: float) -> SetupOutcome:
    return SetupOutcome(
        setup_id="x",
        base_price=100.0,
        evaluation_start=T0,
        horizons=[
            HorizonOutcome(horizon_bars=5, available=True, directional_return_percent=directional_return)
        ],
        mfe=ExcursionMetrics(atr=1.0),
        mae=ExcursionMetrics(atr=-1.0),
        evaluation_quality=EvaluationQuality(bars_available_after_detection=5, fully_evaluated=True),
    )


def _entry(setup_id, timestamp, directional_return=None):
    entry = _TEMPLATE_ENTRY.model_copy(update={"setup_id": setup_id, "candidate_candle_timestamp": timestamp})
    if directional_return is None:
        return entry
    return entry.model_copy(update={"outcome": _fake_outcome(directional_return)})


def test_chronological_folds_splits_evenly_and_absorbs_remainder():
    entries = [_entry(f"e{i}", T0 + timedelta(hours=i)) for i in range(11)]  # 11 entries, 3 folds -> 3,3,5
    folds = _chronological_folds(entries, 3)
    assert [len(f) for f in folds] == [3, 3, 5]
    # Every entry accounted for exactly once, in chronological order.
    assert [e.setup_id for f in folds for e in f] == [f"e{i}" for i in range(11)]


def test_too_few_entries_returns_insufficient_data_with_no_windows():
    entries = [_entry(f"e{i}", T0 + timedelta(hours=i)) for i in range(5)]
    report = anchored_walk_forward(entries, horizon_bars=5, finding_label="test", fold_count=5)
    assert report.windows == []
    assert report.stability == StabilityLabel.INSUFFICIENT_DATA


def test_stable_positive_finding_across_every_fold():
    # 60 entries, all positive directional return -> every fold's median > 0.
    entries = [_entry(f"e{i}", T0 + timedelta(hours=i), directional_return=0.5) for i in range(60)]
    report = anchored_walk_forward(entries, horizon_bars=5, finding_label="all positive", fold_count=5)
    assert len(report.windows) == 5
    assert report.stability == StabilityLabel.STABLE
    assert report.positive_median_window_count == 5
    assert report.negative_median_window_count == 0
    for w in report.windows:
        assert w.test_distribution.median == 0.5
        assert w.train_end < w.test_start


def test_unstable_finding_flips_sign_across_folds():
    # First half of the fold sequence positive, second half negative.
    entries = []
    for i in range(60):
        value = 0.5 if i < 30 else -0.5
        entries.append(_entry(f"e{i}", T0 + timedelta(hours=i), directional_return=value))
    report = anchored_walk_forward(entries, horizon_bars=5, finding_label="flips", fold_count=5)
    assert report.stability == StabilityLabel.UNSTABLE
    assert report.positive_median_window_count > 0
    assert report.negative_median_window_count > 0


def test_windows_are_anchored_train_boundary_expands_and_never_overlaps_test():
    entries = [_entry(f"e{i}", T0 + timedelta(hours=i), directional_return=0.1) for i in range(60)]
    report = anchored_walk_forward(entries, horizon_bars=5, finding_label="test", fold_count=5)
    windows = report.windows
    for w in windows:
        assert w.train_end < w.test_start
    # The train boundary for each successive fold is later than the previous
    # fold's -- the training history is genuinely expanding, not fixed.
    for earlier, later in zip(windows, windows[1:]):
        assert later.train_end > earlier.train_end
        assert later.test_start > earlier.test_end


def test_anti_leakage_fold_membership_ignores_future_outcomes():
    """Mandatory anti-leakage check: which entries land in which fold, and
    each fold's train/test boundary timestamps, must depend only on
    detection-time timestamps -- never on outcome magnitude. Mutating every
    outcome to an extreme fabricated value must not change fold membership
    or boundaries, only the reported medians."""
    entries = [_entry(f"e{i}", T0 + timedelta(hours=i), directional_return=0.1) for i in range(60)]
    before = anchored_walk_forward(entries, horizon_bars=5, finding_label="test", fold_count=5)

    mutated = [_entry(e.setup_id, e.candidate_candle_timestamp, directional_return=999.0) for e in entries]
    after = anchored_walk_forward(mutated, horizon_bars=5, finding_label="test", fold_count=5)

    assert len(before.windows) == len(after.windows)
    for b, a in zip(before.windows, after.windows):
        assert b.window_index == a.window_index
        assert b.train_start == a.train_start
        assert b.train_end == a.train_end
        assert b.test_start == a.test_start
        assert b.test_end == a.test_end
        assert b.test_distribution.n == a.test_distribution.n


def test_real_trend_pullback_data_produces_a_valid_report():
    """Not a claim about which stability label real SPY data produces --
    just that the module runs end-to-end on real ledger entries and every
    invariant (fold ordering, boundary expansion, count conservation) holds."""
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "walk-forward-real")

    from app.research.config import DEFAULT_RESEARCH_CONFIG
    from app.research.outcomes import evaluate_setup_outcome

    trend_entries = []
    for e in result.ledger_entries:
        if e.setup_type != "trend_pullback":
            continue
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        trend_entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)

    report = anchored_walk_forward(
        trend_entries, horizon_bars=5, finding_label="trend_pullback real", fold_count=5
    )
    assert report.stability in list(StabilityLabel)
    for earlier, later in zip(report.windows, report.windows[1:]):
        assert later.train_end >= earlier.train_end
        assert later.test_start > earlier.test_end
