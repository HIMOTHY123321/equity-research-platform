from datetime import datetime, timedelta, timezone

from app.research.replay import run_replay
from app.research.schemas import EvaluationQuality, ExcursionMetrics, HorizonOutcome, SetupOutcome
from app.research_intelligence.episodes import (
    JOIN_ANCHOR,
    JOIN_STRUCTURAL,
    JOIN_TEMPORAL,
    build_episode_memberships,
    build_episodes,
    episode_by_setup_id,
    episode_id,
)
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


def _build_template_entry():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "episode-test")
    return next(e for e in result.ledger_entries if e.detection.reference_source is not None)


# Built once at import time -- every test only needs a valid SetupLedgerEntry
# shape to model_copy() from, not a fresh replay run each time.
_TEMPLATE_ENTRY = _build_template_entry()


def _template_entry():
    return _TEMPLATE_ENTRY


def _entry(
    template,
    setup_id,
    timestamp,
    setup_type="trend_pullback",
    direction="bullish",
    reference_source="nearest_support",
    reference_timestamp=None,
    current_state="qualified",
):
    detection = template.detection.model_copy(
        update={
            "reference_source": reference_source,
            "reference_timestamp": reference_timestamp,
            "current_state": current_state,
        }
    )
    return template.model_copy(
        update={
            "setup_id": setup_id,
            "setup_type": setup_type,
            "direction": direction,
            "candidate_candle_timestamp": timestamp,
            "detection": detection,
        }
    )


T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def test_structural_reference_match_groups_into_one_episode():
    template = _template_entry()
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    entries = [
        _entry(template, "a", T0, reference_timestamp=ref_ts),
        _entry(template, "b", T0 + timedelta(hours=1), reference_timestamp=ref_ts),
        _entry(template, "c", T0 + timedelta(hours=2), reference_timestamp=ref_ts),
    ]
    episodes = build_episodes(entries)
    assert len(episodes) == 1
    assert set(episodes[0].member_setup_ids) == {"a", "b", "c"}
    assert episodes[0].raw_observation_count == 3


def test_temporal_proximity_fallback_when_no_reference():
    template = _template_entry()
    # trend_pullback's own expiration window (from DEFAULT_SETUP_DETECTION_CONFIG)
    # is generous; two bars apart with no reference info should still join.
    entries = [
        _entry(template, "a", T0, reference_source=None),
        _entry(template, "b", T0 + timedelta(hours=1), reference_source=None),
    ]
    episodes = build_episodes(entries)
    assert len(episodes) == 1
    assert set(episodes[0].member_setup_ids) == {"a", "b"}

    memberships = build_episode_memberships(entries)
    assert {m.setup_id: m.join_basis for m in memberships}["b"] == JOIN_TEMPORAL

    lookup = episode_by_setup_id(episodes)
    assert lookup["a"].episode_id == lookup["b"].episode_id == episodes[0].episode_id


def test_new_episode_starts_when_far_apart_with_no_reference():
    template = _template_entry()
    entries = [
        _entry(template, "a", T0, reference_source=None),
        _entry(template, "b", T0 + timedelta(days=30), reference_source=None),
    ]
    episodes = build_episodes(entries)
    assert len(episodes) == 2
    member_sets = {frozenset(e.member_setup_ids) for e in episodes}
    assert member_sets == {frozenset({"a"}), frozenset({"b"})}


def test_different_structural_reference_never_merges_even_if_temporally_close():
    # Both entries HAVE reference info, but it's genuinely different (two
    # distinct swings) -- must NOT fall through to the temporal fallback
    # just because they're an hour apart.
    template = _template_entry()
    ref_a = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    ref_b = datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc)
    entries = [
        _entry(template, "a", T0, reference_timestamp=ref_a),
        _entry(template, "b", T0 + timedelta(hours=1), reference_timestamp=ref_b),
    ]
    episodes = build_episodes(entries)
    assert len(episodes) == 2


def test_different_setup_type_never_merges_even_if_same_timestamp():
    template = _template_entry()
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    entries = [
        _entry(template, "a", T0, setup_type="trend_pullback", reference_timestamp=ref_ts),
        _entry(template, "b", T0, setup_type="breakout_retest", reference_timestamp=ref_ts),
    ]
    episodes = build_episodes(entries)
    assert len(episodes) == 2


def test_different_direction_never_merges():
    template = _template_entry()
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    entries = [
        _entry(template, "a", T0, direction="bullish", reference_timestamp=ref_ts),
        _entry(template, "b", T0 + timedelta(hours=1), direction="bearish", reference_timestamp=ref_ts),
    ]
    episodes = build_episodes(entries)
    assert len(episodes) == 2


def test_join_basis_is_recorded_correctly():
    template = _template_entry()
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    entries = [
        _entry(template, "a", T0, reference_timestamp=ref_ts),
        _entry(template, "b", T0 + timedelta(hours=1), reference_timestamp=ref_ts),
        _entry(template, "c", T0 + timedelta(days=30), reference_source=None),
    ]
    memberships = build_episode_memberships(entries)
    by_id = {m.setup_id: m for m in memberships}
    assert by_id["a"].join_basis == JOIN_ANCHOR
    assert by_id["b"].join_basis == JOIN_STRUCTURAL
    assert by_id["c"].join_basis == JOIN_ANCHOR  # too far from b, starts new episode


def test_episode_id_is_deterministic():
    id_a = episode_id("SPY", "trend_pullback", "bullish", "1h", "setup-1")
    id_b = episode_id("SPY", "trend_pullback", "bullish", "1h", "setup-1")
    assert id_a == id_b
    id_c = episode_id("SPY", "trend_pullback", "bullish", "1h", "setup-2")
    assert id_a != id_c


def test_representative_selection_prefers_first_qualified():
    template = _template_entry()
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    entries = [
        _entry(template, "a", T0, reference_timestamp=ref_ts, current_state="rejected"),
        _entry(template, "b", T0 + timedelta(hours=1), reference_timestamp=ref_ts, current_state="qualified"),
        _entry(template, "c", T0 + timedelta(hours=2), reference_timestamp=ref_ts, current_state="qualified"),
    ]
    episodes = build_episodes(entries)
    assert len(episodes) == 1
    assert episodes[0].representative_setup_id == "b"  # first qualified, not first overall


def test_representative_selection_falls_back_to_first_overall_when_none_qualified():
    template = _template_entry()
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    entries = [
        _entry(template, "a", T0, reference_timestamp=ref_ts, current_state="rejected"),
        _entry(template, "b", T0 + timedelta(hours=1), reference_timestamp=ref_ts, current_state="rejected"),
    ]
    episodes = build_episodes(entries)
    assert episodes[0].representative_setup_id == "a"


def test_qualification_states_represented_is_the_full_set():
    template = _template_entry()
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    entries = [
        _entry(template, "a", T0, reference_timestamp=ref_ts, current_state="rejected"),
        _entry(template, "b", T0 + timedelta(hours=1), reference_timestamp=ref_ts, current_state="qualified"),
    ]
    episodes = build_episodes(entries)
    assert episodes[0].qualification_states_represented == ["qualified", "rejected"]


# ---------------------------------------------------------------------------
# Mandatory anti-leakage test (Phase 9 #36.1): episode identity/membership
# must never be influenced by future outcome data.
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


def test_anti_leakage_episode_membership_ignores_future_outcomes():
    template = _template_entry()
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    entries = [
        _entry(template, "a", T0, reference_timestamp=ref_ts, current_state="rejected"),
        _entry(template, "b", T0 + timedelta(hours=1), reference_timestamp=ref_ts),
    ]
    episodes_before = build_episodes(entries)

    # Wildly different fabricated outcomes -- including flipping which
    # member "looks best" -- must not change grouping OR which member is
    # picked as representative (representative selection is fixed at
    # detection time by qualification state, never by outcome magnitude).
    mutated = [
        entries[0].model_copy(update={"outcome": _fake_outcome(500.0)}),
        entries[1].model_copy(update={"outcome": _fake_outcome(-500.0)}),
    ]
    episodes_after = build_episodes(mutated)

    assert [e.episode_id for e in episodes_before] == [e.episode_id for e in episodes_after]
    assert [sorted(e.member_setup_ids) for e in episodes_before] == [
        sorted(e.member_setup_ids) for e in episodes_after
    ]
    assert [e.representative_setup_id for e in episodes_before] == [
        e.representative_setup_id for e in episodes_after
    ]


def test_anti_leakage_earlier_episode_membership_is_stable_when_later_entries_are_added():
    """A future entry must never retroactively change an earlier entry's
    episode assignment -- membership is decided strictly in chronological
    order, each entry only ever looking at the entry immediately before it,
    never at what comes after."""
    template = _template_entry()
    ref_ts = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    early_entries = [
        _entry(template, "a", T0, reference_timestamp=ref_ts),
        _entry(template, "b", T0 + timedelta(hours=1), reference_timestamp=ref_ts),
    ]
    membership_early_only = {m.setup_id: m.episode_id for m in build_episode_memberships(early_entries)}

    # A later, structurally-different entry appended after the fact --
    # a genuinely new/different swing, far enough away not to fall inside
    # any temporal-proximity window either.
    later_entries = early_entries + [
        _entry(template, "c", T0 + timedelta(days=5), reference_timestamp=ref_ts + timedelta(days=5)),
    ]
    membership_with_future = {m.setup_id: m.episode_id for m in build_episode_memberships(later_entries)}

    assert membership_with_future["a"] == membership_early_only["a"]
    assert membership_with_future["b"] == membership_early_only["b"]


def test_real_trend_pullback_episodes_group_further_than_the_item0_fix_alone():
    """ADR 0009's fix already collapses same-instant-streak duplicates to
    one ledger entry per streak at the detector level -- so at the ledger
    granularity there is no more than one entry per (state, streak). But a
    single swing reference can still produce *several* distinct streaks
    over time (e.g. held -> broken -> re-held), each its own ledger entry,
    all sharing the same underlying swing. Phase 9's episode grouping
    should catch that additional layer of dependence: never *more*
    episodes than entries, and on this real fixture, genuinely fewer."""
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "episode-real-test")
    trend_entries = [e for e in result.ledger_entries if e.setup_type == "trend_pullback"]
    episodes = build_episodes(trend_entries)

    assert len(episodes) <= len(trend_entries)
    assert len(episodes) < len(trend_entries)  # real reduction on this fixture, not a no-op
    multi_member = [e for e in episodes if e.raw_observation_count > 1]
    assert multi_member, "expected at least one multi-entry episode on the real fixture"
    # Every multi-member episode's members must genuinely share a swing
    # reference or sit within that streak's own temporal window -- not an
    # unexplained merge.
    for ep in multi_member:
        assert ep.reference_source is not None
        assert ep.reference_timestamp is not None
