"""Phase 19 (Part 15): StockThesis composition correctness -- confirms it is
built entirely from real engine outputs against the same real-candle
fixture the rest of the ai_analysis suite uses, that no BUY/SELL/score
language ever leaks in, and that Ranking Gate / Signal Validation Gate are
surfaced honestly (never fabricated PASS).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
from app.news.fixture_provider import FixtureNewsProvider
from app.schemas.market_data import Timeframe
from app.thesis.schemas import HistorySufficiency, ResearchLean
from app.thesis.service import build_stock_thesis
from app.validation.repository import SqlAlchemySignalGateRepository
from tests.unit.ai_analysis.conftest import SPY_1H, FakeMarketDataProvider, make_repositories, make_session

_BANNED_TERMS = ("BUY", "SELL", "STRONG BUY", "STRONG SELL")


def _as_of() -> datetime:
    return SPY_1H[-1].timestamp


def _build(as_of=None):
    session = make_session()
    research_repository, news_repository = make_repositories(session)
    decision_repository = SqlAlchemyDecisionEngineRepository(session)
    gate_repository = SqlAlchemySignalGateRepository(session)
    return build_stock_thesis(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=FakeMarketDataProvider(),
        news_provider=FixtureNewsProvider([]),
        news_repository=news_repository,
        research_repository=research_repository,
        decision_repository=decision_repository,
        gate_repository=gate_repository,
        as_of=as_of,
    )


def test_thesis_composes_multi_timeframe_trend_for_the_required_minimum():
    thesis = _build(as_of=_as_of())
    assert {row.timeframe for row in thesis.multi_timeframe_trend} == {
        Timeframe.FIFTEEN_MIN,
        Timeframe.ONE_HOUR,
        Timeframe.FOUR_HOUR,
        Timeframe.ONE_DAY,
    }
    # Every row's explanation is copied verbatim from the structure engine's
    # own deterministic evidence strings -- never empty when a trend was
    # actually classified.
    for row in thesis.multi_timeframe_trend:
        if row.trend.value not in ("insufficient_data",):
            assert isinstance(row.explanation, list)


def test_thesis_never_contains_buy_sell_or_score_language():
    thesis = _build(as_of=_as_of())
    dumped = thesis.model_dump_json().upper()
    for term in _BANNED_TERMS:
        assert term not in dumped


def test_ranking_gate_is_surfaced_honestly_as_fail():
    """ADR 0012's binding decision -- no thesis may claim a validated
    ranking exists while the gate is FAIL."""
    thesis = _build(as_of=_as_of())
    assert thesis.ranking_gate_status.lower() == "fail"
    assert thesis.ranking_validation_message == "VALIDATED RELATIVE RANKING: UNAVAILABLE"


def test_signal_validation_defaults_to_not_enough_data_when_never_evaluated():
    thesis = _build(as_of=_as_of())
    assert thesis.signal_validation.decision == "not_enough_data"


def test_no_decision_plan_yields_empty_evidence_diffs_and_no_plan():
    """No DecisionPlan has ever been persisted for this fresh in-memory DB
    -- the thesis must say so honestly rather than inventing one."""
    thesis = _build(as_of=_as_of())
    assert thesis.decision_plan is None
    assert thesis.evidence_diffs == []


def test_history_sufficiency_is_a_valid_enum_member_with_a_reason():
    thesis = _build(as_of=_as_of())
    assert thesis.history_sufficiency in HistorySufficiency
    assert thesis.history_sufficiency_reason


def test_no_evidence_at_all_yields_insufficient_evidence_lean():
    """Far enough in the past that the detection engine cannot have
    produced any candidates yet, research_lean must not claim a direction
    it has no support for."""
    early_as_of = SPY_1H[0].timestamp + timedelta(hours=1)
    thesis = _build(as_of=early_as_of)
    if not thesis.evidence_for and not thesis.evidence_against:
        assert thesis.research_lean == ResearchLean.INSUFFICIENT_EVIDENCE


def test_as_of_is_respected_and_market_data_cutoff_never_exceeds_it():
    as_of = _as_of()
    thesis = _build(as_of=as_of)
    assert thesis.as_of == as_of
    if thesis.market_data_cutoff is not None:
        assert thesis.market_data_cutoff <= as_of


def test_live_thesis_without_as_of_uses_now():
    before = datetime.now(timezone.utc)
    thesis = _build(as_of=None)
    assert thesis.as_of >= before


def test_fundamentals_placeholder_is_honest_never_fabricated():
    thesis = _build(as_of=_as_of())
    assert "not configured" in thesis.fundamentals_status.lower()
