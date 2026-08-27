import pytest

from app.schemas.market_data import Timeframe
from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.schemas import InteractionType, ZoneEvidenceEntry, ZoneInteraction
from app.support_resistance.strength import (
    compute_confluence_score,
    compute_interaction_score,
    compute_recency_score,
    compute_source_score,
    compute_strength,
)
from tests.conftest import et

TOLERANCE = 1e-9
CONFIG = SupportResistanceConfig()


def evidence_entry(source, weight, price=190.0, timeframe=Timeframe.ONE_DAY):
    ts = et(2026, 8, 17, 9, 30)
    return ZoneEvidenceEntry(
        source=source,
        source_timeframe=timeframe,
        price=price,
        origin_timestamp=ts,
        known_at=ts,
        weight=weight,
    )


def interaction(interaction_type, is_independent=True, hour=9):
    ts = et(2026, 8, 17, hour, 30)
    return ZoneInteraction(
        timestamp=ts,
        interaction_type=interaction_type,
        high=190.1,
        low=189.9,
        close=190.0,
        distance=0.1,
        is_independent=is_independent,
    )


# ---- source score --------------------------------------------------------


def test_source_score_sums_weights():
    evidence = [evidence_entry("previous_week_high", 25), evidence_entry("confirmed_swing_high", 18)]
    assert compute_source_score(evidence, CONFIG) == pytest.approx(43.0, abs=TOLERANCE)


def test_source_score_capped():
    evidence = [evidence_entry("a", 30), evidence_entry("b", 30), evidence_entry("c", 30)]
    assert compute_source_score(evidence, CONFIG) == pytest.approx(CONFIG.source_score_cap, abs=TOLERANCE)


# ---- confluence score ------------------------------------------------------


def test_confluence_score_single_timeframe_is_zero():
    assert compute_confluence_score(1, CONFIG) == pytest.approx(0.0, abs=TOLERANCE)


def test_confluence_score_three_timeframes_matches_worked_example():
    # (3 - 1) * 5 = 10, matching the ADR's worked example exactly.
    assert compute_confluence_score(3, CONFIG) == pytest.approx(10.0, abs=TOLERANCE)


def test_confluence_score_capped():
    assert compute_confluence_score(10, CONFIG) == pytest.approx(CONFIG.confluence_score_cap, abs=TOLERANCE)


# ---- interaction score (diminishing returns) -------------------------------


def test_interaction_score_three_rejections_matches_worked_example():
    # 1st=6, 2nd=4, 3rd=2 -> 12, matching the ADR's worked example exactly.
    interactions = [interaction(InteractionType.REJECTION, hour=h) for h in (9, 10, 11)]
    assert compute_interaction_score(interactions, CONFIG) == pytest.approx(12.0, abs=TOLERANCE)


def test_interaction_score_fourth_rejection_adds_nothing():
    three = [interaction(InteractionType.REJECTION, hour=h) for h in (9, 10, 11)]
    four = three + [interaction(InteractionType.REJECTION, hour=12)]
    assert compute_interaction_score(three, CONFIG) == compute_interaction_score(four, CONFIG)


def test_interaction_score_ignores_non_independent_interactions():
    interactions = [
        interaction(InteractionType.REJECTION, is_independent=True, hour=9),
        interaction(InteractionType.REJECTION, is_independent=False, hour=10),
    ]
    assert compute_interaction_score(interactions, CONFIG) == pytest.approx(6.0, abs=TOLERANCE)


def test_interaction_score_touches_and_rejections_combine_and_cap():
    interactions = [interaction(InteractionType.REJECTION, hour=h) for h in (9, 10, 11)]
    interactions += [interaction(InteractionType.TOUCH, hour=h) for h in (20, 21, 22)]
    # rejection=12, touch=3+2+1=6 -> 18, exactly at the cap
    assert compute_interaction_score(interactions, CONFIG) == pytest.approx(18.0, abs=TOLERANCE)


def test_interaction_score_fifteen_touches_still_capped():
    interactions = [interaction(InteractionType.TOUCH, hour=(9 + h) % 24) for h in range(15)]
    assert compute_interaction_score(interactions, CONFIG) <= CONFIG.interaction_score_cap


# ---- recency score ----------------------------------------------------------


def test_recency_score_buckets():
    assert compute_recency_score(3, CONFIG) == pytest.approx(5.0, abs=TOLERANCE)
    assert compute_recency_score(8, CONFIG) == pytest.approx(3.0, abs=TOLERANCE)
    assert compute_recency_score(25, CONFIG) == pytest.approx(1.0, abs=TOLERANCE)
    assert compute_recency_score(90, CONFIG) == pytest.approx(0.0, abs=TOLERANCE)


def test_recency_score_none_is_zero():
    assert compute_recency_score(None, CONFIG) == pytest.approx(0.0, abs=TOLERANCE)


# ---- full worked example from the ADR --------------------------------------


def test_full_worked_example_matches_adr():
    evidence = [
        evidence_entry("previous_week_high", 25),
        evidence_entry("confirmed_swing_high", 18, timeframe=Timeframe.ONE_DAY),
        evidence_entry("confirmed_swing_high", 12, timeframe=Timeframe.FOUR_HOUR),
    ]
    interactions = [interaction(InteractionType.REJECTION, hour=h) for h in (9, 12, 15)]

    result = compute_strength(
        evidence=evidence,
        timeframe_count=3,
        interactions=interactions,
        bars_since_last_interaction=3,
        is_broken=False,
        config=CONFIG,
    )

    assert result.source_score == pytest.approx(55.0, abs=TOLERANCE)
    assert result.confluence_score == pytest.approx(10.0, abs=TOLERANCE)
    assert result.interaction_score == pytest.approx(12.0, abs=TOLERANCE)
    assert result.recency_score == pytest.approx(5.0, abs=TOLERANCE)
    assert result.total == pytest.approx(82.0, abs=TOLERANCE)


def test_broken_zone_penalty_applied():
    evidence = [evidence_entry("previous_week_high", 25)]
    unbroken = compute_strength(evidence, 1, [], None, is_broken=False, config=CONFIG)
    broken = compute_strength(evidence, 1, [], None, is_broken=True, config=CONFIG)

    assert broken.total == pytest.approx(unbroken.total * 0.3, abs=TOLERANCE)


def test_total_score_never_exceeds_100():
    evidence = [evidence_entry("a", 60)]
    interactions = [interaction(InteractionType.REJECTION, hour=h) for h in (9, 10, 11)]
    result = compute_strength(evidence, 5, interactions, 1, is_broken=False, config=CONFIG)
    assert result.total <= 100.0
