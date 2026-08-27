from datetime import datetime, timezone

from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.outcomes import evaluate_setup_outcome
from app.research.replay import run_replay
from app.research.schemas import EvaluationQuality, ExcursionMetrics, HorizonOutcome, SetupOutcome
from app.research_intelligence.comparison import compare_groups
from app.research_intelligence.schemas import Partition
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _real_entries_with_outcomes():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "comparison-test")
    entries = []
    for e in result.ledger_entries:
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)
    return entries


def _fake_outcome(horizon_bars: int, directional_return: float, mfe_atr=None, mae_atr=None) -> SetupOutcome:
    return SetupOutcome(
        setup_id="fake",
        base_price=100.0,
        evaluation_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        horizons=[
            HorizonOutcome(
                horizon_bars=horizon_bars,
                available=True,
                directional_return_percent=directional_return,
            )
        ],
        mfe=ExcursionMetrics(atr=mfe_atr),
        mae=ExcursionMetrics(atr=mae_atr),
        evaluation_quality=EvaluationQuality(
            bars_available_after_detection=horizon_bars, fully_evaluated=True
        ),
    )


def _fake_group(template_entry, returns: list[float], horizon_bars: int = 5, mfe_atrs=None, mae_atrs=None):
    mfe_atrs = mfe_atrs or [None] * len(returns)
    mae_atrs = mae_atrs or [None] * len(returns)
    return [
        template_entry.model_copy(
            update={
                "setup_id": f"fake-{i}",
                "outcome": _fake_outcome(horizon_bars, r, mfe_atrs[i], mae_atrs[i]),
            }
        )
        for i, r in enumerate(returns)
    ]


def test_hand_calculated_median_and_mean_difference():
    entries = _real_entries_with_outcomes()
    template = entries[0]
    group_a = _fake_group(template, [1.0, 2.0, 3.0])  # median 2.0, mean 2.0
    group_b = _fake_group(template, [4.0, 5.0, 6.0])  # median 5.0, mean 5.0

    result = compare_groups(group_a, group_b, "a", "b", horizon_bars=5, seed=1)
    assert result.median_difference == -3.0
    assert result.mean_difference == -3.0
    assert result.group_a_distribution.n == 3
    assert result.group_b_distribution.n == 3


def test_mfe_mae_atr_median_difference_hand_calculated():
    entries = _real_entries_with_outcomes()
    template = entries[0]
    group_a = _fake_group(template, [1.0, 1.0, 1.0], mfe_atrs=[1.0, 2.0, 3.0], mae_atrs=[-1.0, -2.0, -3.0])
    group_b = _fake_group(template, [1.0, 1.0, 1.0], mfe_atrs=[0.5, 0.5, 0.5], mae_atrs=[-0.5, -0.5, -0.5])

    result = compare_groups(group_a, group_b, "a", "b", horizon_bars=5, seed=1)
    assert result.mfe_atr_median_difference == 1.5  # median(1,2,3)=2.0 - median(0.5,0.5,0.5)=0.5
    assert result.mae_atr_median_difference == -1.5  # median(-1,-2,-3)=-2.0 - (-0.5)


def test_partition_breakdown_is_included_when_mapping_is_supplied():
    entries = _real_entries_with_outcomes()
    template = entries[0]
    group_a = _fake_group(template, [1.0, 2.0])
    group_b = _fake_group(template, [3.0, 4.0])
    mapping = {
        group_a[0].setup_id: Partition.DEVELOPMENT,
        group_a[1].setup_id: Partition.TEST,
        group_b[0].setup_id: Partition.DEVELOPMENT,
        group_b[1].setup_id: Partition.TEST,
    }
    result = compare_groups(group_a, group_b, "a", "b", horizon_bars=5, seed=1, partition_by_setup_id=mapping)
    assert "development" in result.partition_breakdown
    assert "test" in result.partition_breakdown
    dev = result.partition_breakdown["development"]
    assert dev.group_a_n == 1 and dev.group_b_n == 1
    assert dev.median_difference == 1.0 - 3.0


def test_no_partition_mapping_means_no_breakdown():
    entries = _real_entries_with_outcomes()
    template = entries[0]
    group_a = _fake_group(template, [1.0, 2.0])
    group_b = _fake_group(template, [3.0, 4.0])
    result = compare_groups(group_a, group_b, "a", "b", horizon_bars=5, seed=1)
    assert result.partition_breakdown == {}


def test_real_data_qualified_vs_rejected_trend_pullback_produces_a_labeled_comparison():
    entries = _real_entries_with_outcomes()
    trend_entries = [e for e in entries if e.setup_type == "trend_pullback"]
    qualified = [e for e in trend_entries if e.detection.current_state == "qualified"]
    rejected = [e for e in trend_entries if e.detection.current_state == "rejected"]
    assert qualified and rejected

    result = compare_groups(qualified, rejected, "qualified", "rejected", horizon_bars=5, seed=7)
    assert result.group_a_label == "qualified"
    assert result.group_b_label == "rejected"
    assert result.group_a_distribution.n == len(
        [
            e
            for e in qualified
            if e.outcome and any(h.horizon_bars == 5 and h.available for h in e.outcome.horizons)
        ]
    )
    # Below the bootstrap minimum sample -- must be unavailable, not fabricated.
    assert result.median_difference_bootstrap.available is False


def test_empty_group_produces_none_statistics_not_a_crash():
    entries = _real_entries_with_outcomes()
    template = entries[0]
    group_a = _fake_group(template, [1.0, 2.0])
    result = compare_groups(group_a, [], "a", "b", horizon_bars=5, seed=1)
    assert result.median_difference is None
    assert result.cliffs_delta is None
    assert result.group_b_distribution.n == 0
