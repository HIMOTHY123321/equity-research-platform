from datetime import datetime, timedelta, timezone

from app.research.replay import run_replay
from app.research.schemas import EvaluationQuality, ExcursionMetrics, HorizonOutcome, SetupOutcome
from app.research_intelligence.episodes import build_episodes, episode_by_setup_id
from app.research_intelligence.independence import (
    episode_level_sample,
    per_observation_overlap,
    purged_sample,
    sample_composition,
)
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _build_template_entry():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "independence-test")
    return result.ledger_entries[0]


_TEMPLATE_ENTRY = _build_template_entry()
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def _entry(setup_id, symbol, timestamp):
    return _TEMPLATE_ENTRY.model_copy(
        update={"setup_id": setup_id, "symbol": symbol, "candidate_candle_timestamp": timestamp}
    )


def test_purged_sample_excludes_within_window_hand_calculated():
    entries = [
        _entry("a", "SPY", T0),
        _entry("b", "SPY", T0 + timedelta(hours=2)),  # inside a's 5h window
        _entry("c", "SPY", T0 + timedelta(hours=10)),  # outside a's window
    ]
    result = purged_sample(entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert [e.setup_id for e in result] == ["a", "c"]


def test_purged_sample_chains_the_exclusion_window_forward():
    entries = [
        _entry("a", "SPY", T0),
        _entry("b", "SPY", T0 + timedelta(hours=1)),
        _entry("c", "SPY", T0 + timedelta(hours=2)),
        _entry("d", "SPY", T0 + timedelta(hours=3)),
        _entry("e", "SPY", T0 + timedelta(hours=4)),
        _entry("f", "SPY", T0 + timedelta(hours=10)),
    ]
    result = purged_sample(entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert [e.setup_id for e in result] == ["a", "f"]


def test_purged_sample_different_symbols_never_block_each_other():
    entries = [_entry("a", "SPY", T0), _entry("b", "QQQ", T0 + timedelta(hours=1))]
    result = purged_sample(entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert {e.setup_id for e in result} == {"a", "b"}


def test_purged_sample_is_horizon_specific():
    entries = [_entry("a", "SPY", T0), _entry("b", "SPY", T0 + timedelta(hours=8))]
    purged_5 = purged_sample(entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)  # 5h window
    purged_10 = purged_sample(entries, horizon_bars=10, timeframe=Timeframe.ONE_HOUR)  # 10h window
    assert {e.setup_id for e in purged_5} == {"a", "b"}  # 8h gap survives a 5h window
    assert {e.setup_id for e in purged_10} == {"a"}  # but not a 10h window


def test_purged_sample_deterministic_tie_break_on_setup_id():
    entries = [_entry("z", "SPY", T0), _entry("a", "SPY", T0)]
    result = purged_sample(entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)
    assert result[0].setup_id == "a"  # sorted by (timestamp, setup_id) -- "a" < "z"


def test_episode_level_sample_returns_one_representative_per_episode():
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    entries = [
        _TEMPLATE_ENTRY.model_copy(
            update={
                "setup_id": "a",
                "candidate_candle_timestamp": T0,
                "detection": _TEMPLATE_ENTRY.detection.model_copy(
                    update={"reference_source": "nearest_support", "reference_timestamp": ref_ts}
                ),
            }
        ),
        _TEMPLATE_ENTRY.model_copy(
            update={
                "setup_id": "b",
                "candidate_candle_timestamp": T0 + timedelta(hours=1),
                "detection": _TEMPLATE_ENTRY.detection.model_copy(
                    update={"reference_source": "nearest_support", "reference_timestamp": ref_ts}
                ),
            }
        ),
        _entry("c", "QQQ", T0 + timedelta(days=60)),  # unrelated, own episode
    ]
    episodes = build_episodes(entries)
    sample = episode_level_sample(entries, episodes)
    assert len(sample) == 2  # one episode for a+b, one for c
    setup_ids = {e.setup_id for e in sample}
    assert "c" in setup_ids
    assert len(setup_ids & {"a", "b"}) == 1  # exactly one representative from the merged a/b episode


def test_sample_composition_reports_all_three_levels():
    entries = [_entry("a", "SPY", T0), _entry("b", "SPY", T0 + timedelta(hours=1))]
    episodes = build_episodes(entries)
    comp = sample_composition(entries, episodes, Timeframe.ONE_HOUR, horizons=(1, 5))
    assert comp.raw_count == 2
    assert comp.episode_count == len(episodes)
    assert set(comp.purged_counts_by_horizon.keys()) == {1, 5}


def test_per_observation_overlap_hand_calculated_shared_bars():
    entries = [_entry("a", "SPY", T0), _entry("b", "SPY", T0 + timedelta(hours=2))]
    episodes = build_episodes(entries)
    lookup = episode_by_setup_id(episodes)
    details = per_observation_overlap(
        entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR, episode_by_setup_id=lookup
    )
    by_id = {d.setup_id: d for d in details}
    assert by_id["a"].overlap_count == 1
    assert by_id["a"].overlapping_setup_ids == ["b"]
    assert by_id["a"].same_symbol_overlap_count == 1
    # a's 5h window ends at T0+5h; b starts at T0+2h -> 3h = 3 bars shared.
    assert by_id["a"].max_shared_bars == 3
    assert by_id["b"].max_shared_bars == 3


def test_per_observation_overlap_no_overlap_when_far_apart():
    entries = [_entry("a", "SPY", T0), _entry("b", "SPY", T0 + timedelta(hours=10))]
    episodes = build_episodes(entries)
    lookup = episode_by_setup_id(episodes)
    details = per_observation_overlap(
        entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR, episode_by_setup_id=lookup
    )
    assert all(d.overlap_count == 0 for d in details)
    assert all(d.max_shared_bars == 0 for d in details)


def test_per_observation_overlap_distinguishes_same_symbol_and_cross_symbol():
    entries = [
        _entry("a", "SPY", T0),
        _entry("b", "SPY", T0 + timedelta(hours=1)),
        _entry("c", "QQQ", T0 + timedelta(hours=1, minutes=1)),
    ]
    episodes = build_episodes(entries)
    lookup = episode_by_setup_id(episodes)
    details = per_observation_overlap(
        entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR, episode_by_setup_id=lookup
    )
    by_id = {d.setup_id: d for d in details}
    # "a" overlaps both b (same symbol) and, transitively via adjacency, only its immediate neighbor "b".
    assert by_id["a"].same_symbol_overlap_count >= 1


# ---------------------------------------------------------------------------
# Mandatory anti-leakage test (Phase 9 #36.3): purged selection must not use
# outcome magnitude.
# ---------------------------------------------------------------------------


def _fake_outcome(directional_return: float) -> SetupOutcome:
    return SetupOutcome(
        setup_id="x",
        base_price=100.0,
        evaluation_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        horizons=[
            HorizonOutcome(horizon_bars=5, available=True, directional_return_percent=directional_return)
        ],
        mfe=ExcursionMetrics(atr=1.0),
        mae=ExcursionMetrics(atr=-1.0),
        evaluation_quality=EvaluationQuality(bars_available_after_detection=5, fully_evaluated=True),
    )


def test_anti_leakage_purged_selection_ignores_outcome_magnitude():
    entries = [
        _entry("a", "SPY", T0),
        _entry("b", "SPY", T0 + timedelta(hours=2)),
        _entry("c", "SPY", T0 + timedelta(hours=10)),
    ]
    before = purged_sample(entries, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)

    mutated = [
        entries[0].model_copy(update={"outcome": _fake_outcome(500.0)}),
        entries[1].model_copy(update={"outcome": _fake_outcome(-500.0)}),
        entries[2].model_copy(update={"outcome": _fake_outcome(0.001)}),
    ]
    after = purged_sample(mutated, horizon_bars=5, timeframe=Timeframe.ONE_HOUR)

    assert [e.setup_id for e in before] == [e.setup_id for e in after]
