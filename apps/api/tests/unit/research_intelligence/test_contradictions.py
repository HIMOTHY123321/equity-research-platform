from datetime import datetime, timezone

from app.market_structure.schemas import Direction, TrendClass
from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.outcomes import evaluate_setup_outcome
from app.research.replay import run_replay
from app.research.schemas import EvaluationQuality, ExcursionMetrics, HorizonOutcome, SetupOutcome
from app.research_intelligence.contradictions import (
    BUILTIN_ASSUMPTIONS,
    check_all_builtin_assumptions,
    check_assumption,
)
from app.research_intelligence.schemas import ContradictionStatus
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupContext, SetupFingerprint, SetupType
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _template_entry():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "contradiction-test")
    return next(e for e in result.ledger_entries if e.detection.fingerprint is not None)


def _entry(
    template,
    setup_id,
    directional_return,
    direction=Direction.BULLISH,
    daily_structure=TrendClass.BULLISH,
    rvol=2.0,
    support_confluence=2,
    resistance_confluence=2,
    setup_type=None,
    current_state=None,
    horizon_bars=5,
):
    resolved_setup_type = setup_type or template.detection.setup_type
    fp = SetupFingerprint(
        setup_type=resolved_setup_type,
        direction=direction,
        daily_structure=daily_structure,
        support_confluence=support_confluence,
        resistance_confluence=resistance_confluence,
    )
    context = SetupContext(as_of=datetime(2026, 1, 1, tzinfo=timezone.utc), rvol=rvol)
    detection = template.detection.model_copy(
        update={
            "direction": direction,
            "fingerprint": fp,
            "context": context,
            "setup_type": resolved_setup_type,
            "current_state": current_state or template.detection.current_state,
        }
    )
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
            "detection": detection,
            "setup_type": resolved_setup_type.value,
            "direction": direction.value,
            "outcome": outcome,
        }
    )


def test_higher_timeframe_alignment_supported_when_aligned_outperforms():
    template = _template_entry()
    aligned = [
        _entry(template, f"a{i}", 0.5, daily_structure=TrendClass.BULLISH, direction=Direction.BULLISH)
        for i in range(5)
    ]
    opposed = [
        _entry(template, f"b{i}", -0.5, daily_structure=TrendClass.BEARISH, direction=Direction.BULLISH)
        for i in range(5)
    ]
    assumption = next(a for a in BUILTIN_ASSUMPTIONS if a.code == "higher_timeframe_alignment_helps")
    result = check_assumption(assumption, aligned + opposed, horizon_bars=5, seed=1)
    assert result.status == ContradictionStatus.SUPPORTED
    assert result.comparison.median_difference > 0


def test_higher_timeframe_alignment_not_supported_when_data_contradicts_it():
    template = _template_entry()
    # Deliberately the OPPOSITE of the assumption: "aligned" underperforms.
    aligned = [
        _entry(template, f"a{i}", -0.3, daily_structure=TrendClass.BULLISH, direction=Direction.BULLISH)
        for i in range(5)
    ]
    opposed = [
        _entry(template, f"b{i}", 0.4, daily_structure=TrendClass.BEARISH, direction=Direction.BULLISH)
        for i in range(5)
    ]
    assumption = next(a for a in BUILTIN_ASSUMPTIONS if a.code == "higher_timeframe_alignment_helps")
    result = check_assumption(assumption, aligned + opposed, horizon_bars=5, seed=1)
    assert result.status == ContradictionStatus.NOT_SUPPORTED


def test_rvol_confirmation_assumption_hand_calculated():
    template = _template_entry()
    confirmed = [_entry(template, f"a{i}", 0.6, rvol=2.5) for i in range(5)]
    unconfirmed = [_entry(template, f"b{i}", 0.1, rvol=0.8) for i in range(5)]
    assumption = next(a for a in BUILTIN_ASSUMPTIONS if a.code == "rvol_confirmation_helps")
    result = check_assumption(assumption, confirmed + unconfirmed, horizon_bars=5, seed=1)
    assert result.status == ContradictionStatus.SUPPORTED
    assert result.group_a_label == "rvol_confirmed"
    assert result.group_b_label == "rvol_not_confirmed"


def test_sr_confluence_assumption_hand_calculated():
    template = _template_entry()
    confluent = [
        _entry(template, f"a{i}", 0.4, support_confluence=2, resistance_confluence=1) for i in range(5)
    ]
    not_confluent = [
        _entry(template, f"b{i}", -0.1, support_confluence=0, resistance_confluence=0) for i in range(5)
    ]
    assumption = next(a for a in BUILTIN_ASSUMPTIONS if a.code == "sr_confluence_helps")
    result = check_assumption(assumption, confluent + not_confluent, horizon_bars=5, seed=1)
    assert result.status == ContradictionStatus.SUPPORTED


def test_qualification_breakout_assumption_scopes_to_breakout_retest_only():
    template = _template_entry()
    qualified_breakout = [
        _entry(template, f"a{i}", 0.3, setup_type=SetupType.BREAKOUT_RETEST, current_state="qualified")
        for i in range(5)
    ]
    rejected_breakout = [
        _entry(template, f"b{i}", -0.2, setup_type=SetupType.BREAKOUT_RETEST, current_state="rejected")
        for i in range(5)
    ]
    # A different setup type entirely -- must NOT be included in either group.
    other_type = [
        _entry(template, f"c{i}", 5.0, setup_type=SetupType.TREND_PULLBACK, current_state="qualified")
        for i in range(3)
    ]
    assumption = next(a for a in BUILTIN_ASSUMPTIONS if a.code == "qualification_improves_breakout_behavior")
    result = check_assumption(
        assumption, qualified_breakout + rejected_breakout + other_type, horizon_bars=5, seed=1
    )
    assert result.status == ContradictionStatus.SUPPORTED
    assert result.comparison.group_a_distribution.n == 5
    assert result.comparison.group_b_distribution.n == 5


def test_insufficient_data_status_when_a_group_is_empty():
    template = _template_entry()
    only_aligned = [_entry(template, f"a{i}", 0.5, daily_structure=TrendClass.BULLISH) for i in range(5)]
    assumption = next(a for a in BUILTIN_ASSUMPTIONS if a.code == "higher_timeframe_alignment_helps")
    result = check_assumption(assumption, only_aligned, horizon_bars=5, seed=1)
    assert result.status == ContradictionStatus.INSUFFICIENT_DATA


def test_check_all_builtin_assumptions_covers_all_four():
    entries, _ = _real_entries_and_baseline()
    results = check_all_builtin_assumptions(entries, horizon_bars=5, seed=1)
    assert {r.assumption_code for r in results} == {a.code for a in BUILTIN_ASSUMPTIONS}


def _real_entries_and_baseline():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "contradiction-real")
    entries = []
    for e in result.ledger_entries:
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)
    return entries, result.baseline_samples
