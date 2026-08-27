import math
from datetime import datetime, timezone

from app.market_structure.schemas import Direction, TrendClass
from app.research.replay import run_replay
from app.research.schemas import EvaluationQuality, ExcursionMetrics, HorizonOutcome, SetupOutcome
from app.research_intelligence.analogs import (
    analog_diversity_report,
    attach_outcomes,
    distance_between,
    diverse_analogs,
    extract_features,
    rank_analogs,
)
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
from app.research_intelligence.episodes import SetupEpisode
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupContext, SetupFingerprint, SetupType
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _template_entry():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "analog-test")
    return next(e for e in result.ledger_entries if e.detection.fingerprint is not None)


def _features(
    setup_type=SetupType.BREAKOUT_RETEST,
    direction=Direction.BULLISH,
    daily=TrendClass.BULLISH,
    four_hour=TrendClass.BULLISH,
    one_hour=TrendClass.BULLISH,
    rvol_bucket="1.5-2.0",
    gap_state="none",
    resistance_confluence=2,
    support_confluence=1,
    detection_close=100.0,
    nearest_support=98.0,
    nearest_resistance=103.0,
    ema20=99.0,
    range_high=105.0,
    range_low=95.0,
):
    fp = SetupFingerprint(
        setup_type=setup_type,
        direction=direction,
        daily_structure=daily,
        four_hour_structure=four_hour,
        one_hour_structure=one_hour,
        rvol_bucket=rvol_bucket,
        gap_state=gap_state,
        support_confluence=support_confluence,
        resistance_confluence=resistance_confluence,
    )
    context = SetupContext(
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        nearest_support_price=nearest_support,
        nearest_resistance_price=nearest_resistance,
        ema20=ema20,
        active_range_high=range_high,
        active_range_low=range_low,
    )

    class _Candidate:
        pass

    c = _Candidate()
    c.setup_type = setup_type
    c.direction = direction
    c.fingerprint = fp
    c.context = context
    return extract_features(c, detection_close)


def test_identical_features_produce_zero_distance():
    a = _features()
    b = _features()
    result = distance_between(a, b)
    assert math.isclose(result.distance, 0.0, abs_tol=1e-9)
    assert result.differing_dimensions == []
    assert set(result.matched_dimensions) == {
        "setup_type",
        "direction",
        "daily_structure",
        "four_hour_structure",
        "one_hour_structure",
        "rvol_bucket",
        "gap_state",
        "resistance_confluence",
        "support_confluence",
        "distance_to_support_percent",
        "distance_to_resistance_percent",
        "ma20_relative_percent",
        "range_position",
    }


def test_categorical_mismatch_increases_distance():
    a = _features(direction=Direction.BULLISH)
    b = _features(direction=Direction.BEARISH)
    baseline = distance_between(a, a)
    mismatched = distance_between(a, b)
    assert mismatched.distance > baseline.distance
    assert "direction" in mismatched.differing_dimensions


def test_numeric_mismatch_increases_distance_proportionally():
    a = _features(nearest_support=98.0)
    close_b = _features(nearest_support=97.9)  # tiny difference
    far_b = _features(nearest_support=50.0)  # huge difference
    close_dist = distance_between(a, close_b)
    far_dist = distance_between(a, far_b)
    assert far_dist.distance > close_dist.distance


def test_missing_dimensions_are_explicit_not_nan():
    a = _features()
    b = _features(rvol_bucket=None, ema20=None)
    result = distance_between(a, b)
    assert "rvol_bucket" in result.missing_dimensions
    assert "ma20_relative_percent" in result.missing_dimensions
    assert not math.isnan(result.distance)
    for entry in result.breakdown:
        assert not math.isnan(entry.contribution)


def test_no_nan_anywhere_across_many_combinations():
    variants = [
        _features(rvol_bucket=None),
        _features(ema20=None, nearest_support=None),
        _features(resistance_confluence=0, support_confluence=0),
        _features(range_high=None, range_low=None),
    ]
    for v in variants:
        result = distance_between(_features(), v)
        assert not math.isnan(result.distance)
        assert all(not math.isnan(e.contribution) for e in result.breakdown)


def test_deterministic_ranking_and_tie_breaking():
    template = _template_entry()
    query = _features()

    e1 = template.model_copy(update={"setup_id": "b-tie"})
    e2 = template.model_copy(update={"setup_id": "a-tie"})
    candidates = [(e1, _features()), (e2, _features())]  # identical features -> tied distance

    ranked_a = rank_analogs(query, candidates, top_n=10)
    ranked_b = rank_analogs(query, candidates, top_n=10)
    assert [r.setup_id for r in ranked_a] == [r.setup_id for r in ranked_b]
    # Tie-break is by setup_id, so "a-tie" sorts before "b-tie".
    assert [r.setup_id for r in ranked_a] == ["a-tie", "b-tie"]


def test_identical_case_ranks_first_among_dissimilar_candidates():
    template = _template_entry()
    query = _features()
    identical = template.model_copy(update={"setup_id": "identical"})
    different = template.model_copy(update={"setup_id": "different"})

    candidates = [
        (different, _features(direction=Direction.BEARISH, daily=TrendClass.BEARISH)),
        (identical, _features()),
    ]
    ranked = rank_analogs(query, candidates, top_n=10)
    assert ranked[0].setup_id == "identical"
    assert math.isclose(ranked[0].distance.distance, 0.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Mandatory anti-leakage test (#28): mutating ONLY a case's future outcome
# must never change its similarity ranking.
# ---------------------------------------------------------------------------


def test_anti_leakage_changing_future_outcome_does_not_change_ranking():
    template = _template_entry()
    query = _features()

    entry_a = template.model_copy(update={"setup_id": "case-1"})
    entry_b = template.model_copy(update={"setup_id": "case-2"})
    candidates = [(entry_a, _features(nearest_support=97.0)), (entry_b, _features(nearest_support=90.0))]

    ranked_before = rank_analogs(query, candidates, top_n=10)

    def fake_outcome(directional_return):
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

    # Wildly different future outcomes attached to the SAME underlying
    # detection-time features -- ranking must be untouched.
    entry_a_mutated = entry_a.model_copy(update={"outcome": fake_outcome(50.0)})
    entry_b_mutated = entry_b.model_copy(update={"outcome": fake_outcome(-50.0)})
    candidates_mutated = [
        (entry_a_mutated, _features(nearest_support=97.0)),
        (entry_b_mutated, _features(nearest_support=90.0)),
    ]
    ranked_after = rank_analogs(query, candidates_mutated, top_n=10)

    assert [r.setup_id for r in ranked_before] == [r.setup_id for r in ranked_after]
    assert [r.distance.distance for r in ranked_before] == [r.distance.distance for r in ranked_after]


def test_attach_outcomes_never_reorders_or_rescores_the_ranking():
    template = _template_entry()
    query = _features()
    entry_a = template.model_copy(update={"setup_id": "case-1"})
    entry_b = template.model_copy(update={"setup_id": "case-2"})
    candidates = [(entry_a, _features(nearest_support=97.0)), (entry_b, _features(nearest_support=90.0))]
    ranked = rank_analogs(query, candidates, top_n=10)
    original_order = [r.setup_id for r in ranked]
    original_distances = [r.distance.distance for r in ranked]

    entries_by_id = {"case-1": entry_a.model_copy(update={"outcome": None}), "case-2": entry_b}
    decorated = attach_outcomes(ranked, entries_by_id)

    assert [r.setup_id for r in decorated] == original_order
    assert [r.distance.distance for r in decorated] == original_distances


def test_attach_outcomes_fills_in_horizon_returns():
    template = _template_entry()
    query = _features()
    entry = template.model_copy(update={"setup_id": "case-1"})
    outcome = SetupOutcome(
        setup_id="case-1",
        base_price=100.0,
        evaluation_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        horizons=[
            HorizonOutcome(horizon_bars=1, available=True, directional_return_percent=0.1),
            HorizonOutcome(horizon_bars=5, available=True, directional_return_percent=0.5),
            HorizonOutcome(horizon_bars=10, available=False),
        ],
        mfe=ExcursionMetrics(atr=1.2),
        mae=ExcursionMetrics(atr=-0.5),
        evaluation_quality=EvaluationQuality(bars_available_after_detection=5, fully_evaluated=False),
    )
    entry = entry.model_copy(update={"outcome": outcome})
    ranked = rank_analogs(query, [(entry, _features())], top_n=10)
    decorated = attach_outcomes(ranked, {"case-1": entry})

    assert decorated[0].outcome.one_bar_directional_return_percent == 0.1
    assert decorated[0].outcome.five_bar_directional_return_percent == 0.5
    assert decorated[0].outcome.ten_bar_directional_return_percent is None  # not available
    assert decorated[0].outcome.mfe_atr == 1.2
    assert decorated[0].outcome.mae_atr == -0.5


def test_extract_features_from_real_candidate_does_not_crash():
    entry = _template_entry()
    from app.research_intelligence.analogs import detection_close_for

    detection_close = detection_close_for(entry.detection, {SYMBOL: SPY_1H})
    features = extract_features(entry.detection, detection_close)
    assert features.setup_type == entry.detection.setup_type.value


def test_default_analog_top_n_is_respected():
    template = _template_entry()
    query = _features()
    candidates = [
        (template.model_copy(update={"setup_id": f"e{i}"}), _features(nearest_support=90.0 + i))
        for i in range(DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.analog_top_n + 5)
    ]
    ranked = rank_analogs(query, candidates)
    assert len(ranked) == DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.analog_top_n


# ---------------------------------------------------------------------------
# Analog diversity (Phase 9 #20/#21): read-only over an already-ranked list.
# ---------------------------------------------------------------------------


def _episode(episode_id: str, member_setup_ids: list) -> SetupEpisode:
    return SetupEpisode(
        episode_id=episode_id,
        setup_type="breakout_retest",
        direction="bullish",
        symbol="SPY",
        timeframe="1h",
        member_setup_ids=member_setup_ids,
        first_detected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_member_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        qualification_states_represented=["qualified"],
        raw_observation_count=len(member_setup_ids),
        representative_setup_id=member_setup_ids[0],
    )


def _ranked(setup_ids, symbols=None):
    """Every candidate uses identical features (tied distance = 0), so the
    ranking order is purely the deterministic setup_id tie-break -- which
    for these fixture ids ("a" < "b" < "c" < "d") matches insertion order,
    making the resulting list easy to reason about in the tests below."""
    template = _template_entry()
    query = _features()
    symbols = symbols or ["SPY"] * len(setup_ids)
    candidates = [
        (template.model_copy(update={"setup_id": sid, "symbol": sym}), _features())
        for sid, sym in zip(setup_ids, symbols)
    ]
    return rank_analogs(query, candidates, top_n=len(setup_ids))


def test_diverse_analogs_keeps_only_the_first_occurrence_per_episode():
    ranked = _ranked(["a", "b", "c", "d"])
    # "a" and "b" share episode-1; "c" is alone; "d" has no episode data.
    episode_by_setup_id = {
        "a": _episode("episode-1", ["a", "b"]),
        "b": _episode("episode-1", ["a", "b"]),
        "c": _episode("episode-2", ["c"]),
    }
    diverse = diverse_analogs(ranked, episode_by_setup_id)
    setup_ids = [r.setup_id for r in diverse]
    assert setup_ids == ["a", "c", "d"]  # "b" dropped -- same episode as "a", which ranked first


def test_diverse_analogs_never_touches_distance_or_order_of_survivors():
    ranked = _ranked(["a", "b", "c"])
    episode_by_setup_id = {"a": _episode("episode-1", ["a", "b"]), "b": _episode("episode-1", ["a", "b"])}
    diverse = diverse_analogs(ranked, episode_by_setup_id)
    ranked_by_id = {r.setup_id: r for r in ranked}
    for r in diverse:
        assert r.distance.distance == ranked_by_id[r.setup_id].distance.distance


def test_diverse_analogs_respects_limit():
    ranked = _ranked(["a", "b", "c", "d"])
    diverse = diverse_analogs(ranked, {}, limit=2)
    assert len(diverse) == 2


def test_analog_diversity_report_flags_repeated_episode():
    ranked = _ranked(["a", "b", "c"])
    episode_by_setup_id = {"a": _episode("episode-1", ["a", "b"]), "b": _episode("episode-1", ["a", "b"])}
    report = analog_diversity_report(ranked, episode_by_setup_id)
    assert report.total_analogs == 3
    assert report.max_same_episode_count == 2
    assert report.distinct_episode_count == 1
    assert report.analogs_without_episode_data == 1  # "c"
    assert report.warning is not None
    assert "SAME_EPISODE_ANALOGS" in report.warning


def test_analog_diversity_report_flags_symbol_concentration():
    ranked = _ranked(["a", "b", "c", "d"], symbols=["SPY", "SPY", "SPY", "QQQ"])
    report = analog_diversity_report(ranked, {})
    assert report.dominant_symbol == "SPY"
    assert report.dominant_symbol_share == 0.75
    assert "SYMBOL_CONCENTRATION" in report.warning


def test_analog_diversity_report_no_warning_when_genuinely_diverse():
    ranked = _ranked(["a", "b", "c", "d"], symbols=["SPY", "QQQ", "NVDA", "AAPL"])
    episode_by_setup_id = {
        "a": _episode("episode-1", ["a"]),
        "b": _episode("episode-2", ["b"]),
        "c": _episode("episode-3", ["c"]),
        "d": _episode("episode-4", ["d"]),
    }
    report = analog_diversity_report(ranked, episode_by_setup_id)
    assert report.warning is None
    assert report.max_same_episode_count == 1


def test_anti_leakage_analog_diversity_ignores_future_outcomes():
    """Mandatory anti-leakage check: diversity filtering and the warning
    computation must depend only on episode/symbol membership, never on
    outcome. Attaching outcomes after ranking must not change either."""
    ranked = _ranked(["a", "b", "c"])
    episode_by_setup_id = {"a": _episode("episode-1", ["a", "b"]), "b": _episode("episode-1", ["a", "b"])}
    before_report = analog_diversity_report(ranked, episode_by_setup_id)
    before_diverse = [r.setup_id for r in diverse_analogs(ranked, episode_by_setup_id)]

    entries_by_id = {
        r.setup_id: _template_entry().model_copy(
            update={
                "setup_id": r.setup_id,
                "outcome": SetupOutcome(
                    setup_id=r.setup_id,
                    base_price=100.0,
                    evaluation_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    horizons=[
                        HorizonOutcome(horizon_bars=5, available=True, directional_return_percent=999.0)
                    ],
                    mfe=ExcursionMetrics(atr=1.0),
                    mae=ExcursionMetrics(atr=-1.0),
                    evaluation_quality=EvaluationQuality(
                        bars_available_after_detection=5, fully_evaluated=True
                    ),
                ),
            }
        )
        for r in ranked
    }
    decorated = attach_outcomes(ranked, entries_by_id)

    after_report = analog_diversity_report(decorated, episode_by_setup_id)
    after_diverse = [r.setup_id for r in diverse_analogs(decorated, episode_by_setup_id)]

    assert before_report == after_report
    assert before_diverse == after_diverse
