from app.market_structure.schemas import Direction
from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.outcomes import evaluate_setup_outcome
from app.research.replay import run_replay
from app.research_intelligence.excursions import excursion_profile, first_hit_analysis
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import hour_bar, load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _template_entry():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "excursion-test")
    return result.ledger_entries[0]


def _synthetic_entry(template, direction: Direction, detection_bar, atr=2.0):
    candidate = template.detection.model_copy(
        update={
            "direction": direction,
            "candidate_candle_timestamp": detection_bar.timestamp,
            "context": template.detection.context.model_copy(update={"atr": atr}),
        }
    )
    return template.model_copy(update={"detection": candidate, "setup_id": "synthetic"})


def test_favorable_first_bullish():
    template = _template_entry()
    detection = hour_bar(1, 9, 100.5, 99.5, close=100.0)
    bar1 = hour_bar(1, 10, 103.0, 99.0, close=101.0)  # favorable_delta=3>=2, adverse_delta=-1 not<=-2
    entry = _synthetic_entry(template, Direction.BULLISH, detection)
    candles = {SYMBOL: [detection, bar1]}

    result = first_hit_analysis([entry], candles, favorable_atr_threshold=1.0, adverse_atr_threshold=1.0)
    assert result.favorable_first_count == 1
    assert result.adverse_first_count == 0
    assert result.neither_count == 0


def test_adverse_first_bullish():
    template = _template_entry()
    detection = hour_bar(1, 9, 100.5, 99.5, close=100.0)
    bar1 = hour_bar(1, 10, 101.0, 97.0, close=99.0)  # adverse_delta=-3<=-2, favorable_delta=1 not>=2
    entry = _synthetic_entry(template, Direction.BULLISH, detection)
    candles = {SYMBOL: [detection, bar1]}

    result = first_hit_analysis([entry], candles, favorable_atr_threshold=1.0, adverse_atr_threshold=1.0)
    assert result.adverse_first_count == 1
    assert result.favorable_first_count == 0


def test_neither_hit_within_the_available_path():
    template = _template_entry()
    detection = hour_bar(1, 9, 100.5, 99.5, close=100.0)
    bar1 = hour_bar(1, 10, 101.0, 99.0, close=100.0)  # inside both thresholds
    entry = _synthetic_entry(template, Direction.BULLISH, detection)
    candles = {SYMBOL: [detection, bar1]}

    result = first_hit_analysis([entry], candles, favorable_atr_threshold=1.0, adverse_atr_threshold=1.0)
    assert result.neither_count == 1


def test_ambiguous_same_bar_defaults_to_adverse_first():
    template = _template_entry()
    detection = hour_bar(1, 9, 100.5, 99.5, close=100.0)
    bar1 = hour_bar(1, 10, 105.0, 95.0, close=100.0)  # both thresholds crossed in one bar
    entry = _synthetic_entry(template, Direction.BULLISH, detection)
    candles = {SYMBOL: [detection, bar1]}

    result = first_hit_analysis([entry], candles, favorable_atr_threshold=1.0, adverse_atr_threshold=1.0)
    assert result.adverse_first_count == 1
    assert result.favorable_first_count == 0


def test_bearish_symmetry_favorable_is_a_downward_move():
    template = _template_entry()
    detection = hour_bar(1, 9, 100.5, 99.5, close=100.0)
    bar1 = hour_bar(1, 10, 101.0, 97.0, close=98.0)  # low=97 -> favorable (down) delta=3>=2 for bearish
    entry = _synthetic_entry(template, Direction.BEARISH, detection)
    candles = {SYMBOL: [detection, bar1]}

    result = first_hit_analysis([entry], candles, favorable_atr_threshold=1.0, adverse_atr_threshold=1.0)
    assert result.favorable_first_count == 1


def test_excluded_when_atr_is_unavailable():
    template = _template_entry()
    detection = hour_bar(1, 9, 100.5, 99.5, close=100.0)
    entry = _synthetic_entry(template, Direction.BULLISH, detection, atr=None)
    candles = {SYMBOL: [detection, hour_bar(1, 10, 103.0, 99.0, close=101.0)]}

    result = first_hit_analysis([entry], candles, favorable_atr_threshold=1.0, adverse_atr_threshold=1.0)
    assert result.excluded_no_atr_count == 1
    assert result.sample_count == 1


def test_excluded_when_symbol_has_no_candle_series():
    template = _template_entry()
    detection = hour_bar(1, 9, 100.5, 99.5, close=100.0)
    entry = _synthetic_entry(template, Direction.BULLISH, detection)

    result = first_hit_analysis([entry], {}, favorable_atr_threshold=1.0, adverse_atr_threshold=1.0)
    assert result.excluded_no_atr_count == 1


def test_default_thresholds_come_from_config_when_not_supplied():
    from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG

    template = _template_entry()
    detection = hour_bar(1, 9, 100.5, 99.5, close=100.0)
    entry = _synthetic_entry(template, Direction.BULLISH, detection)
    candles = {SYMBOL: [detection, hour_bar(1, 10, 103.0, 99.0, close=101.0)]}

    result = first_hit_analysis([entry], candles)
    assert result.favorable_atr_threshold == DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.first_hit_favorable_atr
    assert result.adverse_atr_threshold == DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.first_hit_adverse_atr


def test_excursion_profile_hand_calculated_medians():
    from datetime import datetime, timezone

    from app.research.schemas import EvaluationQuality, ExcursionMetrics, HorizonOutcome, SetupOutcome

    template = _template_entry()

    def fake_entry(setup_id, mfe_pct, mfe_atr, mae_pct, mae_atr, bars_mfe, bars_mae):
        outcome = SetupOutcome(
            setup_id=setup_id,
            base_price=100.0,
            evaluation_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            horizons=[HorizonOutcome(horizon_bars=5, available=True, directional_return_percent=0.1)],
            mfe=ExcursionMetrics(percent=mfe_pct, atr=mfe_atr, bars_until=bars_mfe),
            mae=ExcursionMetrics(percent=mae_pct, atr=mae_atr, bars_until=bars_mae),
            evaluation_quality=EvaluationQuality(bars_available_after_detection=5, fully_evaluated=True),
        )
        return template.model_copy(update={"setup_id": setup_id, "outcome": outcome})

    entries = [
        fake_entry("e1", 1.0, 1.0, -0.5, -0.5, 2, 1),
        fake_entry("e2", 2.0, 2.0, -1.0, -1.0, 4, 3),
        fake_entry("e3", 3.0, 3.0, -1.5, -1.5, 6, 5),
    ]
    profile = excursion_profile(entries)
    assert profile.sample_count == 3
    assert profile.mfe_percent.median == 2.0
    assert profile.mfe_atr.median == 2.0
    assert profile.mae_percent.median == -1.0
    assert profile.mae_atr.median == -1.0
    assert profile.bars_to_mfe.median == 4
    assert profile.bars_to_mae.median == 3


def test_excursion_profile_on_real_data_produces_no_crash_and_reasonable_signs():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "excursion-real")
    entries = []
    for e in result.ledger_entries:
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)

    profile = excursion_profile(entries)
    assert profile.sample_count == len(entries)
    if profile.mfe_atr.n > 0:
        assert profile.mfe_atr.median >= 0  # MFE is always >= 0 by convention
    if profile.mae_atr.n > 0:
        assert profile.mae_atr.median <= 0  # MAE is always <= 0 by convention
