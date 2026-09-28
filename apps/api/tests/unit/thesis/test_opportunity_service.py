"""Phase 19 (Part 15): Opportunity Intelligence composition -- confirms the
universe is respected, per-symbol failures are isolated (one bad symbol
must not break the whole list), Ranking Gate is always surfaced as
UNAVAILABLE (ADR 0012 is still FAIL), and no BUY/SELL/score language leaks
into any candidate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.alerts.repository import SqlAlchemyAlertRepository
from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
from app.market_data.provider import MarketDataProvider
from app.monitoring.universe import MonitoringUniverse
from app.schemas.market_data import Timeframe
from app.thesis.opportunity_schemas import AttentionCategory
from app.thesis.opportunity_service import build_opportunities
from app.validation.repository import SqlAlchemySignalGateRepository
from tests.unit.ai_analysis.conftest import SPY_1H, make_session

_BANNED_TERMS = ("BUY", "SELL", "STRONG BUY", "STRONG SELL")


class _FakeProvider(MarketDataProvider):
    def __init__(self, fail_symbols: tuple[str, ...] = ()):
        self._fail_symbols = fail_symbols

    def get_candles(self, symbol, timeframe, limit=200):
        if symbol in self._fail_symbols:
            raise RuntimeError(f"provider unavailable for {symbol}")
        if symbol == "SPY" and timeframe.value in ("1h", "4h", "1d"):
            return SPY_1H[-limit:]
        return []

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def _build(session, provider, universe_symbols=("SPY", "QQQ"), **kwargs):
    alert_repository = SqlAlchemyAlertRepository(session)
    universe = MonitoringUniverse(alert_repository, default_symbols=universe_symbols)
    decision_repository = SqlAlchemyDecisionEngineRepository(session)
    gate_repository = SqlAlchemySignalGateRepository(session)
    return build_opportunities(
        timeframe=Timeframe.ONE_HOUR,
        market_provider=provider,
        universe=universe,
        decision_repository=decision_repository,
        gate_repository=gate_repository,
        provider_name="fake",
        as_of=SPY_1H[-1].timestamp,
        **kwargs,
    )


def test_every_universe_symbol_produces_a_candidate():
    response = _build(make_session(), _FakeProvider())
    symbols = {c.symbol for c in response.candidates}
    assert symbols == {"SPY", "QQQ"}


def test_a_failing_symbol_does_not_break_the_rest_of_the_list():
    response = _build(make_session(), _FakeProvider(fail_symbols=("QQQ",)))
    symbols = {c.symbol for c in response.candidates}
    assert symbols == {"SPY"}


def test_ranking_validation_message_is_always_unavailable():
    response = _build(make_session(), _FakeProvider())
    assert response.ranking_validation_message == "VALIDATED RELATIVE RANKING: UNAVAILABLE"
    for candidate in response.candidates:
        assert candidate.ranking_gate_status.lower() == "fail"


def test_no_open_decision_plan_yields_near_setup_watching_or_insufficient_data():
    response = _build(make_session(), _FakeProvider())
    allowed = {
        AttentionCategory.NEAR_SETUP,
        AttentionCategory.WATCHING,
        AttentionCategory.INSUFFICIENT_DATA,
    }
    for candidate in response.candidates:
        assert candidate.decision_plan_id is None
        assert candidate.category in allowed


def test_no_buy_sell_or_score_language_anywhere_in_the_response():
    response = _build(make_session(), _FakeProvider())
    dumped = response.model_dump_json().upper()
    for term in _BANNED_TERMS:
        assert term not in dumped


def test_category_filter_narrows_results():
    session = make_session()
    provider = _FakeProvider()
    full = _build(session, provider)
    present_categories = {c.category for c in full.candidates}
    target = next(iter(present_categories))
    filtered = _build(make_session(), provider, category=target)
    assert all(c.category == target for c in filtered.candidates)


def test_live_call_without_as_of_uses_now():
    before = datetime.now(timezone.utc)
    session = make_session()
    alert_repository = SqlAlchemyAlertRepository(session)
    universe = MonitoringUniverse(alert_repository, default_symbols=("SPY",))
    response = build_opportunities(
        timeframe=Timeframe.ONE_HOUR,
        market_provider=_FakeProvider(),
        universe=universe,
        decision_repository=SqlAlchemyDecisionEngineRepository(session),
        gate_repository=SqlAlchemySignalGateRepository(session),
        provider_name="fake",
    )
    assert response.as_of >= before
