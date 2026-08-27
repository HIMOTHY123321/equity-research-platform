"""Expanded MFE/MAE research (#19) and first-hit path analysis (#20).
`excursion_profile` turns Phase 7's per-entry `SetupOutcome.mfe`/`.mae`
(the single best excursion in the whole evaluation window) into cohort
distributions. `first_hit_analysis` answers a different, more granular
question that a single MFE/MAE value can't: for two *arbitrary* configurable
ATR thresholds, which was reached first, bar by bar -- so it re-walks the
same forward candle path `app.research.outcomes` already knows how to build
(`forward_candles`, `directional_delta`), rather than re-deriving it.

Both are descriptive historical path statistics. Neither is a trading stop
or target -- nothing here recommends an entry, exit, or position size.
"""

from __future__ import annotations

from typing import Optional

from app.market_structure.schemas import Direction
from app.research.outcomes import directional_delta, forward_candles
from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import ExcursionProfile, FirstHitOutcome, FirstHitResult
from app.research_intelligence.statistics import summarize_distribution
from app.schemas.market_data import Candle


def excursion_profile(entries: list[SetupLedgerEntry]) -> ExcursionProfile:
    mfe_percent, mfe_atr, mae_percent, mae_atr, bars_to_mfe, bars_to_mae = [], [], [], [], [], []
    for entry in entries:
        if entry.outcome is None:
            continue
        if entry.outcome.mfe.percent is not None:
            mfe_percent.append(entry.outcome.mfe.percent)
        if entry.outcome.mfe.atr is not None:
            mfe_atr.append(entry.outcome.mfe.atr)
        if entry.outcome.mfe.bars_until is not None:
            bars_to_mfe.append(entry.outcome.mfe.bars_until)
        if entry.outcome.mae.percent is not None:
            mae_percent.append(entry.outcome.mae.percent)
        if entry.outcome.mae.atr is not None:
            mae_atr.append(entry.outcome.mae.atr)
        if entry.outcome.mae.bars_until is not None:
            bars_to_mae.append(entry.outcome.mae.bars_until)

    return ExcursionProfile(
        mfe_percent=summarize_distribution(mfe_percent),
        mfe_atr=summarize_distribution(mfe_atr),
        mae_percent=summarize_distribution(mae_percent),
        mae_atr=summarize_distribution(mae_atr),
        bars_to_mfe=summarize_distribution(bars_to_mfe),
        bars_to_mae=summarize_distribution(bars_to_mae),
        sample_count=len(entries),
    )


def _first_hit_for_entry(
    entry: SetupLedgerEntry,
    candles_by_symbol: dict[str, list[Candle]],
    favorable_atr_threshold: float,
    adverse_atr_threshold: float,
) -> Optional[FirstHitOutcome]:
    """None means "excluded" -- no ATR available at detection time, or no
    candle series supplied for this entry's symbol."""
    candidate = entry.detection
    atr = candidate.context.atr if candidate.context else None
    candles = candles_by_symbol.get(candidate.symbol)
    if not atr or not candles:
        return None

    detection_candle = next((c for c in candles if c.timestamp == candidate.candidate_candle_timestamp), None)
    if detection_candle is None:
        return None
    base_price = detection_candle.close
    future = forward_candles(candles, candidate.candidate_candle_timestamp)

    for bar in future:
        favorable_price = bar.high if candidate.direction == Direction.BULLISH else bar.low
        adverse_price = bar.low if candidate.direction == Direction.BULLISH else bar.high
        favorable_delta = directional_delta(favorable_price, base_price, candidate.direction)
        adverse_delta = directional_delta(adverse_price, base_price, candidate.direction)

        favorable_hit = (favorable_delta / atr) >= favorable_atr_threshold
        adverse_hit = (adverse_delta / atr) <= -adverse_atr_threshold

        if favorable_hit and adverse_hit:
            # Both thresholds fall within the same bar -- OHLC alone can't
            # order intra-bar events, and this codebase never guesses at
            # intra-bar sequencing. The conservative convention (standard
            # in backtesting when this ambiguity is unresolvable) is to
            # assume the worse outcome: adverse-first.
            return FirstHitOutcome.ADVERSE_FIRST
        if favorable_hit:
            return FirstHitOutcome.FAVORABLE_FIRST
        if adverse_hit:
            return FirstHitOutcome.ADVERSE_FIRST

    return FirstHitOutcome.NEITHER


def first_hit_analysis(
    entries: list[SetupLedgerEntry],
    candles_by_symbol: dict[str, list[Candle]],
    favorable_atr_threshold: Optional[float] = None,
    adverse_atr_threshold: Optional[float] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> FirstHitResult:
    favorable_atr_threshold = (
        favorable_atr_threshold if favorable_atr_threshold is not None else config.first_hit_favorable_atr
    )
    adverse_atr_threshold = (
        adverse_atr_threshold if adverse_atr_threshold is not None else config.first_hit_adverse_atr
    )

    counts = {
        FirstHitOutcome.FAVORABLE_FIRST: 0,
        FirstHitOutcome.ADVERSE_FIRST: 0,
        FirstHitOutcome.NEITHER: 0,
    }
    excluded = 0
    for entry in entries:
        outcome = _first_hit_for_entry(
            entry, candles_by_symbol, favorable_atr_threshold, adverse_atr_threshold
        )
        if outcome is None:
            excluded += 1
        else:
            counts[outcome] += 1

    return FirstHitResult(
        favorable_atr_threshold=favorable_atr_threshold,
        adverse_atr_threshold=adverse_atr_threshold,
        sample_count=len(entries),
        favorable_first_count=counts[FirstHitOutcome.FAVORABLE_FIRST],
        adverse_first_count=counts[FirstHitOutcome.ADVERSE_FIRST],
        neither_count=counts[FirstHitOutcome.NEITHER],
        excluded_no_atr_count=excluded,
    )
