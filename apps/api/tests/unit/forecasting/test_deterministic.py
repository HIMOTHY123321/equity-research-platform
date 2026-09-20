"""Phase 12 (#B/#C): deterministic forecast generators -- every branch
either returns a value from the closed set (#D "no invented outcome types")
or abstains with a specific, honest reason. Each generator only reads a
fixed slice of the EvidencePacket, so tests use lightweight SimpleNamespace
fakes for that slice (same rationale as test_evidence_quality.py); the
"happy path" against a real pipeline-built packet is covered by
test_service.py and the sanity check in test_resolver.py.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.forecasting.config import DEFAULT_FORECAST_CONFIG
from app.forecasting.deterministic import (
    generate_catalyst_reaction_forecast,
    generate_direction_forecast,
    generate_setup_outcome_forecast,
    generate_structure_forecast,
    generate_volatility_forecast,
)
from app.forecasting.schemas import (
    AbstentionReason,
    CatalystReactionForecastValue,
    StructureForecastValue,
    VolatilityForecastValue,
)
from app.news.schemas import CatalystReference, SetupCatalystContext, SetupCatalystContextLabel

_CONFIG = DEFAULT_FORECAST_CONFIG


def _empty_research():
    return None  # no historical_research -> classify_evidence_quality is INSUFFICIENT_EVIDENCE


def _candidate(direction="bullish", setup_type="breakout_retest", candidate_id="cand-1", qualified=True):
    return SimpleNamespace(
        id=candidate_id,
        direction=SimpleNamespace(value=direction),
        setup_type=SimpleNamespace(value=setup_type),
        current_state=SimpleNamespace(value="qualified" if qualified else "invalidated"),
    )


def _packet(
    setup=None, historical_research=None, sr=None, features=None, catalyst_context=None, qualified=True
):
    setup_section = None
    if setup is not None:
        setup_section = SimpleNamespace(candidate=setup, qualified=qualified)
    return SimpleNamespace(
        setup=setup_section,
        historical_research=historical_research,
        support_resistance=sr or SimpleNamespace(nearest_support=None, nearest_resistance=None),
        features=features or SimpleNamespace(atr=None, intraday_relative_volume=None),
        catalyst_context=catalyst_context,
    )


# ---------------------------------------------------------------- DIRECTION


def test_direction_abstains_with_no_setup():
    decision = generate_direction_forecast(_packet(setup=None), _CONFIG)
    assert decision.abstained
    assert decision.abstention_reason == AbstentionReason.INSUFFICIENT_HISTORICAL_ANALOGS


def test_direction_abstains_when_evidence_insufficient():
    decision = generate_direction_forecast(_packet(setup=_candidate(), historical_research=None), _CONFIG)
    assert decision.abstained


# ---------------------------------------------------------------- STRUCTURE


def test_structure_abstains_with_no_setup():
    decision = generate_structure_forecast(_packet(setup=None), _CONFIG)
    assert decision.abstained
    assert decision.abstention_reason == AbstentionReason.INSUFFICIENT_HISTORICAL_ANALOGS


def test_structure_abstains_when_no_zone_on_the_setups_side():
    sr = SimpleNamespace(nearest_support=None, nearest_resistance=None)
    decision = generate_structure_forecast(_packet(setup=_candidate(direction="bullish"), sr=sr), _CONFIG)
    assert decision.abstained


def test_structure_bullish_targets_nearest_resistance_break():
    zone = SimpleNamespace(id="zone-1")
    sr = SimpleNamespace(nearest_support=None, nearest_resistance=zone)
    decision = generate_structure_forecast(_packet(setup=_candidate(direction="bullish"), sr=sr), _CONFIG)
    assert not decision.abstained
    assert decision.forecast_value == StructureForecastValue.RESISTANCE_BREAKS.value
    assert decision.zone_ref == "zone-1"
    assert "zone:zone-1" in decision.evidence_refs


def test_structure_bearish_targets_nearest_support_fail():
    zone = SimpleNamespace(id="zone-2")
    sr = SimpleNamespace(nearest_support=zone, nearest_resistance=None)
    decision = generate_structure_forecast(_packet(setup=_candidate(direction="bearish"), sr=sr), _CONFIG)
    assert decision.forecast_value == StructureForecastValue.SUPPORT_FAILS.value
    assert decision.zone_ref == "zone-2"


# ---------------------------------------------------------------- VOLATILITY


def test_volatility_abstains_without_atr_or_rvol():
    decision = generate_volatility_forecast(_packet(), _CONFIG)
    assert decision.abstained
    assert decision.abstention_reason == AbstentionReason.STALE_DATA


def test_volatility_expands_on_high_rvol():
    features = SimpleNamespace(
        atr=SimpleNamespace(value=1.5), intraday_relative_volume=SimpleNamespace(intraday_relative_volume=2.0)
    )
    decision = generate_volatility_forecast(_packet(features=features), _CONFIG)
    assert decision.forecast_value == VolatilityForecastValue.EXPANDS.value


def test_volatility_contracts_on_low_rvol():
    features = SimpleNamespace(
        atr=SimpleNamespace(value=1.5), intraday_relative_volume=SimpleNamespace(intraday_relative_volume=0.4)
    )
    decision = generate_volatility_forecast(_packet(features=features), _CONFIG)
    assert decision.forecast_value == VolatilityForecastValue.CONTRACTS.value


# ------------------------------------------------------------ SETUP_OUTCOME


def test_setup_outcome_abstains_with_no_setup():
    decision = generate_setup_outcome_forecast(_packet(setup=None), _CONFIG)
    assert decision.abstained


def test_setup_outcome_abstains_when_not_qualified():
    decision = generate_setup_outcome_forecast(_packet(setup=_candidate(), qualified=False), _CONFIG)
    assert decision.abstained
    assert decision.abstention_reason == AbstentionReason.RANKING_GATE_RESTRICTION


def test_setup_outcome_abstains_on_insufficient_evidence_even_when_qualified():
    decision = generate_setup_outcome_forecast(
        _packet(setup=_candidate(), qualified=True, historical_research=None), _CONFIG
    )
    assert decision.abstained


# -------------------------------------------------------------- CATALYST


def _catalyst_context(label):
    return SetupCatalystContext(
        setup_id="cand-1",
        symbol="SPY",
        nearest_catalyst=CatalystReference(
            event_id="evt-1", category="earnings", primary_timestamp="2026-06-01T12:00:00Z", source_count=1
        ),
        label=label,
        label_basis="test fixture",
    )


def test_catalyst_reaction_abstains_with_no_catalyst_context():
    decision = generate_catalyst_reaction_forecast(_packet(catalyst_context=None), _CONFIG)
    assert decision.abstained
    assert decision.abstention_reason == AbstentionReason.CATALYST_AMBIGUITY


def test_catalyst_reaction_abstains_on_timing_ambiguous():
    ctx = _catalyst_context(SetupCatalystContextLabel.CATALYST_TIMING_AMBIGUOUS)
    decision = generate_catalyst_reaction_forecast(_packet(catalyst_context=ctx), _CONFIG)
    assert decision.abstained


def test_catalyst_reaction_abstains_when_already_resolved():
    ctx = _catalyst_context(SetupCatalystContextLabel.CATALYST_REACTION_FADED)
    decision = generate_catalyst_reaction_forecast(_packet(catalyst_context=ctx), _CONFIG)
    assert decision.abstained


def test_catalyst_reaction_persists_forecast_from_supported_label():
    ctx = _catalyst_context(SetupCatalystContextLabel.CATALYST_SUPPORTED)
    decision = generate_catalyst_reaction_forecast(_packet(catalyst_context=ctx), _CONFIG)
    assert decision.forecast_value == CatalystReactionForecastValue.PERSISTS.value
    assert decision.evidence_refs == ["catalyst:evt-1"]


def test_catalyst_reaction_fades_forecast_from_conflicted_label():
    ctx = _catalyst_context(SetupCatalystContextLabel.CATALYST_CONFLICTED)
    decision = generate_catalyst_reaction_forecast(_packet(catalyst_context=ctx), _CONFIG)
    assert decision.forecast_value == CatalystReactionForecastValue.FADES.value
