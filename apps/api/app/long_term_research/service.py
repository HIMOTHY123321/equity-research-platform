"""Orchestration for the Long-Term Research daily scan -- the single
entry point both the manual "RUN LONG-TERM SCAN" button and the
externally-triggered scheduled job call into (see
app.api.routes.long_term_research). Wholly separate from
app.decision_engine/app.alerts: no DecisionPlan, no AlertEvent, no
short-term state is read or written anywhere in this module.

Determinism: for a fixed `symbols`/`as_of` and fixed provider responses,
`run_scan` always produces the same LongTermResearchResult list -- all
the actual computation is delegated to the pure functions in
app.long_term_research.factors and app.long_term_research.rules; this
module's only job is fetching inputs, calling them, persisting the
output, and (only on a genuine state TRANSITION into a push-worthy
state) dispatching a push. A snapshot is always persisted BEFORE any
push attempt, so a Pushover outage can never affect what gets recorded.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.config import Settings
from app.long_term_research.factors import build_factor_bundle
from app.long_term_research.fundamentals import (
    FundamentalsProvider,
    FundamentalsProviderError,
)
from app.long_term_research.push import ProviderFactory, dispatch_long_term_research_push
from app.long_term_research.repository import LongTermResearchRepository
from app.long_term_research.rules import determine_research_state
from app.long_term_research.schemas import (
    PUSH_WORTHY_STATES,
    FundamentalsSnapshot,
    LongTermResearchResult,
)
from app.long_term_research.summary import render_plain_english_summary
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import Timeframe

logger = logging.getLogger(__name__)

CANDLES_REQUESTED = 800
"""Enough daily bars for a 200-day SMA plus roughly 3 years of EPS/price
history for the "valuation relative to own history" comparison -- see
app.long_term_research.factors.compute_valuation."""


def _fetch_fundamentals(provider: FundamentalsProvider, symbol: str, as_of: datetime) -> FundamentalsSnapshot:
    try:
        return provider.get_fundamentals(symbol)
    except FundamentalsProviderError:
        logger.warning("Fundamentals unavailable for symbol=%s -- treating as all-missing", symbol)
        return FundamentalsSnapshot(symbol=symbol, fetched_at=as_of, provider="unavailable")


def run_scan(
    symbols: list[str],
    *,
    as_of: datetime,
    repository: LongTermResearchRepository,
    market_data_provider: MarketDataProvider,
    fundamentals_provider: FundamentalsProvider,
    settings: Optional[Settings] = None,
    push_provider_factory: Optional[ProviderFactory] = None,
) -> list[LongTermResearchResult]:
    results: list[LongTermResearchResult] = []

    for symbol in symbols:
        try:
            candles = market_data_provider.get_candles(
                symbol, Timeframe.ONE_DAY, limit=CANDLES_REQUESTED, before=as_of
            )
        except Exception:  # noqa: BLE001 -- one symbol's provider failure must not abort the whole scan
            logger.exception("Candle fetch failed for symbol=%s during long-term scan", symbol)
            candles = []

        fundamentals = _fetch_fundamentals(fundamentals_provider, symbol, as_of)

        bounded_sorted = sorted((c for c in candles if c.timestamp <= as_of), key=lambda c: c.timestamp)
        price = bounded_sorted[-1].close if bounded_sorted else None

        factors = build_factor_bundle(fundamentals, candles, as_of)
        rule_result = determine_research_state(factors)

        result = LongTermResearchResult(
            symbol=symbol,
            as_of=as_of,
            price=price,
            research_state=rule_result.state,
            factors=factors,
            evidence_quality=rule_result.evidence_quality,
            positive_evidence=rule_result.positive_evidence,
            negative_evidence=rule_result.negative_evidence,
            contradictions=rule_result.contradictions,
            missing_evidence=rule_result.missing_evidence,
            reason=rule_result.reason,
            what_would_change_state=rule_result.what_would_change_state,
            market_data_provider=type(market_data_provider).__name__,
            fundamentals_provider=fundamentals.provider,
        )
        result = result.model_copy(update={"ai_summary": render_plain_english_summary(result)})

        previous = repository.get_latest_snapshot(symbol)

        # Persisted BEFORE any push attempt -- a Pushover failure below
        # can never prevent or corrupt this record.
        repository.insert_snapshot(result)
        results.append(result)

        transitioned_into_push_worthy = result.research_state in PUSH_WORTHY_STATES and (
            previous is None or previous.research_state != result.research_state
        )
        if transitioned_into_push_worthy:
            candidate_user_ids = repository.list_push_eligible_user_ids(symbol)
            if candidate_user_ids:
                dispatch_long_term_research_push(
                    repository,
                    result,
                    candidate_user_ids,
                    settings=settings,
                    provider_factory=push_provider_factory,
                )

    return results
