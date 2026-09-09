"""Phase 11.1 (#E/#G): historical analog ranking must be blind to outcome
data -- two ledger entries with identical detection-time state but
different (future) outcomes must rank/distance identically; outcome only
enters the picture in a strictly later, separate decoration pass.
"""

from __future__ import annotations

from datetime import timedelta

from app.ai_analysis.market_snapshot import build_market_snapshot
from app.research.schemas import (
    EvaluationQuality,
    ExcursionMetrics,
    HorizonOutcome,
    SetupLedgerEntry,
    SetupOutcome,
)
from app.research_intelligence.analogs import (
    attach_outcomes,
    detection_close_for,
    extract_features,
    rank_analogs,
)
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1H, FakeMarketDataProvider


def _real_candidate():
    provider = FakeMarketDataProvider()
    snapshot = build_market_snapshot("SPY", Timeframe.ONE_HOUR, provider, SPY_1H[-1].timestamp)
    pool = (
        snapshot.setup_snapshot.qualified_setups
        + snapshot.setup_snapshot.candidates
        + snapshot.setup_snapshot.rejected_candidates
    )
    assert pool
    return pool[0]


def _outcome(setup_id: str, mfe_percent: float) -> SetupOutcome:
    now = SPY_1H[-1].timestamp
    return SetupOutcome(
        setup_id=setup_id,
        base_price=100.0,
        detection_atr=1.0,
        evaluation_start=now,
        evaluation_end=now + timedelta(hours=5),
        horizons=[
            HorizonOutcome(
                horizon_bars=5,
                available=True,
                future_close=101.0,
                absolute_change=1.0,
                raw_return_percent=1.0,
                directional_return_percent=1.0,
            )
        ],
        mfe=ExcursionMetrics(
            absolute=mfe_percent, percent=mfe_percent, atr=mfe_percent, bars_until=2, timestamp=now
        ),
        mae=ExcursionMetrics(absolute=-0.5, percent=-0.5, atr=-0.5, bars_until=1, timestamp=now),
        evaluation_quality=EvaluationQuality(
            bars_available_after_detection=5, fully_evaluated=True, warnings=[]
        ),
    )


def _ledger_entry(candidate, mfe_percent: float) -> SetupLedgerEntry:
    return SetupLedgerEntry(
        research_run_id="00000000-0000-0000-0000-000000000000",
        setup_id=candidate.id,
        symbol=candidate.symbol,
        timeframe=candidate.timeframe.value,
        setup_type=candidate.setup_type.value,
        direction=candidate.direction.value,
        first_seen_at=candidate.candidate_candle_timestamp,
        candidate_candle_timestamp=candidate.candidate_candle_timestamp,
        detection=candidate,
        current_state=candidate.current_state.value,
        last_observed_at=candidate.candidate_candle_timestamp,
        latest=candidate,
        outcome=_outcome(candidate.id, mfe_percent),
    )


def test_extract_features_never_touches_outcome():
    candidate = _real_candidate()
    candles_by_symbol = {"SPY": SPY_1H}
    close = detection_close_for(candidate, candles_by_symbol)

    entry_small_outcome = _ledger_entry(candidate, mfe_percent=0.1)
    entry_huge_outcome = _ledger_entry(candidate, mfe_percent=999.0)

    features_a = extract_features(entry_small_outcome.detection, close)
    features_b = extract_features(entry_huge_outcome.detection, close)
    assert features_a == features_b


def test_ranking_distance_is_unaffected_by_which_outcome_is_attached():
    candidate = _real_candidate()
    candles_by_symbol = {"SPY": SPY_1H}
    close = detection_close_for(candidate, candles_by_symbol)
    query_features = extract_features(candidate, close)

    entry_small = _ledger_entry(candidate, mfe_percent=0.1)
    entry_huge = _ledger_entry(candidate, mfe_percent=999.0)

    candidates_small = [(entry_small, extract_features(entry_small.detection, close))]
    candidates_huge = [(entry_huge, extract_features(entry_huge.detection, close))]

    ranked_small = rank_analogs(query_features, candidates_small)
    ranked_huge = rank_analogs(query_features, candidates_huge)

    assert ranked_small[0].distance.distance == ranked_huge[0].distance.distance
    assert ranked_small[0].distance.breakdown == ranked_huge[0].distance.breakdown

    # Outcome enters only in this strictly-later, separate pass.
    decorated_small = attach_outcomes(ranked_small, {entry_small.setup_id: entry_small})
    decorated_huge = attach_outcomes(ranked_huge, {entry_huge.setup_id: entry_huge})
    assert decorated_small[0].outcome != decorated_huge[0].outcome
