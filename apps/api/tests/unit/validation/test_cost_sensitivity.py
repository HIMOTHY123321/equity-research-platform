"""Phase 15 §13/§14: cost sensitivity is a labeled research haircut on
already-observed returns, never a fill simulation."""

from __future__ import annotations

from app.validation.cost_sensitivity import DEFAULT_COST_SCENARIOS_BPS, apply_cost_sensitivity


def test_zero_bps_scenario_matches_raw_returns():
    points = apply_cost_sensitivity([1.0, 2.0, 3.0])
    zero = next(p for p in points if p.cost_bps == 0.0)
    assert zero.median_return_after_cost == 2.0
    assert zero.positive_rate_after_cost == 1.0


def test_larger_cost_assumption_reduces_returns_more():
    points = apply_cost_sensitivity([1.0, 1.0, 1.0])
    by_bps = {p.cost_bps: p for p in points}
    assert by_bps[2.0].median_return_after_cost > by_bps[20.0].median_return_after_cost


def test_edge_disappearing_under_cost_is_visible():
    # A tiny raw edge (0.05%) should flip negative under a 10bps (0.10%) cost.
    points = apply_cost_sensitivity([0.05, 0.05, 0.05])
    by_bps = {p.cost_bps: p for p in points}
    assert by_bps[0.0].median_return_after_cost > 0
    assert by_bps[10.0].median_return_after_cost < 0


def test_empty_returns_produce_no_fabricated_values():
    points = apply_cost_sensitivity([])
    for point in points:
        assert point.median_return_after_cost is None
        assert point.positive_rate_after_cost is None


def test_default_scenarios_are_the_documented_set():
    assert DEFAULT_COST_SCENARIOS_BPS == (0.0, 2.0, 5.0, 10.0, 20.0)
