"""Phase 12 (#D): AI-synthesis forecast origin. Nothing a provider returns
is trusted until independently validated -- an invented value, an
unresolvable evidence ref, banned/BUY-SELL language, or provider
unavailability must all abstain, never silently fall back to a partial or
patched result.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.ai_analysis.claims import ClaimDirection, ClaimStrength, EvidenceClaim
from app.forecasting.ai_forecast import (
    ForecastSelectionProvider,
    ForecastSelectionUnavailable,
    RawForecastSelection,
    select_ai_forecast,
)
from app.forecasting.schemas import AbstentionReason, DirectionForecastValue, ForecastCategory


def _claim(evidence_refs):
    return EvidenceClaim(
        claim_id="claim-1",
        claim_type="setup_direction",
        statement="test claim",
        evidence_refs=evidence_refs,
        direction=ClaimDirection.NEUTRAL,
        strength=ClaimStrength.MODERATE,
    )


@dataclass
class _StaticProvider(ForecastSelectionProvider):
    forecast_value: str
    evidence_refs: list[str]
    rationale: str = "grounded rationale citing setup:cand-1"
    name: str = "static"

    def select(self, packet, claims, category, allowed_values):
        return RawForecastSelection(self.forecast_value, self.evidence_refs, self.rationale)


class _UnavailableProvider(ForecastSelectionProvider):
    name = "unavailable"

    def select(self, packet, claims, category, allowed_values):
        raise ForecastSelectionUnavailable("no credentials configured")


def test_valid_selection_is_accepted():
    claims = [_claim(["setup:cand-1"])]
    provider = _StaticProvider(forecast_value=DirectionForecastValue.UP.value, evidence_refs=["setup:cand-1"])
    decision = select_ai_forecast(_fake_packet(), claims, ForecastCategory.DIRECTION, provider)
    assert not decision.abstained
    assert decision.forecast_value == DirectionForecastValue.UP.value


def test_provider_unavailable_abstains_with_provider_limitation():
    decision = select_ai_forecast(_fake_packet(), [], ForecastCategory.DIRECTION, _UnavailableProvider())
    assert decision.abstained
    assert decision.abstention_reason == AbstentionReason.PROVIDER_LIMITATION


def test_ai_cannot_invent_a_forecast_value_outside_the_closed_set():
    claims = [_claim(["setup:cand-1"])]
    provider = _StaticProvider(forecast_value="strong_buy", evidence_refs=["setup:cand-1"])
    decision = select_ai_forecast(_fake_packet(), claims, ForecastCategory.DIRECTION, provider)
    assert decision.abstained
    assert decision.abstention_reason == AbstentionReason.PROVIDER_LIMITATION


def test_buy_sell_language_as_a_forecast_value_is_rejected():
    claims = [_claim(["setup:cand-1"])]
    provider = _StaticProvider(forecast_value="BUY", evidence_refs=["setup:cand-1"])
    decision = select_ai_forecast(_fake_packet(), claims, ForecastCategory.DIRECTION, provider)
    assert decision.abstained


def test_ai_cannot_cite_an_evidence_ref_outside_the_supplied_claims():
    claims = [_claim(["setup:cand-1"])]
    provider = _StaticProvider(
        forecast_value=DirectionForecastValue.UP.value, evidence_refs=["setup:invented-999"]
    )
    decision = select_ai_forecast(_fake_packet(), claims, ForecastCategory.DIRECTION, provider)
    assert decision.abstained
    assert decision.abstention_reason == AbstentionReason.PROVIDER_LIMITATION


def test_empty_evidence_refs_is_rejected():
    claims = [_claim(["setup:cand-1"])]
    provider = _StaticProvider(forecast_value=DirectionForecastValue.UP.value, evidence_refs=[])
    decision = select_ai_forecast(_fake_packet(), claims, ForecastCategory.DIRECTION, provider)
    assert decision.abstained


@pytest.mark.parametrize(
    "banned_rationale",
    [
        "This is a STRONG BUY signal.",
        "I'm 90% confident this will go up.",
        "Guaranteed to rally from here.",
    ],
)
def test_banned_rationale_language_causes_abstention(banned_rationale):
    claims = [_claim(["setup:cand-1"])]
    provider = _StaticProvider(
        forecast_value=DirectionForecastValue.UP.value,
        evidence_refs=["setup:cand-1"],
        rationale=banned_rationale,
    )
    decision = select_ai_forecast(_fake_packet(), claims, ForecastCategory.DIRECTION, provider)
    assert decision.abstained
    assert decision.abstention_reason == AbstentionReason.PROVIDER_LIMITATION


def _fake_packet():
    from types import SimpleNamespace

    return SimpleNamespace(historical_research=None)
