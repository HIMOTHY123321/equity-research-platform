"""The single entry point for Phase 7: fetched candles -> a completed,
persisted research run. Provider-independent (#26) -- every candle list is
already fetched and normalized by the caller (the API route); this module
never imports a concrete MarketDataProvider.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from app.features.config import DEFAULT_FEATURE_CONFIG, FeatureConfig
from app.market_structure.config import DEFAULT_MARKET_STRUCTURE_CONFIG, MarketStructureConfig
from app.research.baseline import compute_regime_matched_baseline, compute_unconditional_baseline
from app.research.config import DEFAULT_RESEARCH_CONFIG, ResearchConfig
from app.research.config_hash import build_config_snapshot, compute_config_hash
from app.research.outcomes import evaluate_setup_outcome
from app.research.provenance import build_dataset_provenance
from app.research.replay import run_replay
from app.research.repository import ResearchRepository
from app.research.schemas import BaselineComparison, ResearchRunSummary, SetupTypeSummary
from app.research.summary import group_outcome_stats, qualification_lift, rejection_value
from app.schemas.market_data import Candle, Timeframe
from app.setup_detection.config import DEFAULT_SETUP_DETECTION_CONFIG, SetupDetectionConfig
from app.support_resistance.config import DEFAULT_SUPPORT_RESISTANCE_CONFIG, SupportResistanceConfig

_LIVE_STATES = ("qualified", "triggered")


def execute_research_run(
    *,
    symbol: str,
    timeframe: Timeframe,
    start_date: datetime,
    end_date: datetime,
    primary_candles: list[Candle],
    daily_candles: list[Candle],
    four_hour_candles: list[Candle],
    provider_name: str,
    repository: ResearchRepository,
    feature_config: FeatureConfig = DEFAULT_FEATURE_CONFIG,
    structure_config: MarketStructureConfig = DEFAULT_MARKET_STRUCTURE_CONFIG,
    levels_config: SupportResistanceConfig = DEFAULT_SUPPORT_RESISTANCE_CONFIG,
    setup_config: SetupDetectionConfig = DEFAULT_SETUP_DETECTION_CONFIG,
    research_config: ResearchConfig = DEFAULT_RESEARCH_CONFIG,
) -> str:
    config_snapshot = build_config_snapshot(
        feature_config, structure_config, levels_config, setup_config, research_config
    )
    config_hash = compute_config_hash(config_snapshot)
    provenance = build_dataset_provenance(
        provider_name, symbol, timeframe.value, start_date, end_date, primary_candles
    )

    run_id = repository.create_run(
        symbol=symbol,
        timeframe=timeframe.value,
        start_date=start_date,
        end_date=end_date,
        config_hash=config_hash,
        config_snapshot=config_snapshot,
        dataset_provenance=provenance,
    )

    try:
        replay_result = run_replay(
            symbol,
            timeframe,
            start_date,
            end_date,
            primary_candles,
            daily_candles,
            four_hour_candles,
            run_id,
            feature_config,
            structure_config,
            levels_config,
            setup_config,
            research_config,
        )

        entries = []
        for entry in replay_result.ledger_entries:
            outcome = evaluate_setup_outcome(entry.detection, primary_candles, research_config)
            entries.append(entry.model_copy(update={"outcome": outcome}) if outcome else entry)

        qualified = [e for e in entries if e.current_state in _LIVE_STATES]
        rejected = [e for e in entries if e.current_state == "rejected"]

        setup_types = sorted({e.setup_type for e in entries})
        setup_type_summaries = []
        for setup_type in setup_types:
            type_qualified = [e for e in qualified if e.setup_type == setup_type]
            type_rejected = [e for e in rejected if e.setup_type == setup_type]

            baseline = _build_baseline(
                type_qualified, primary_candles, replay_result.baseline_samples, research_config
            )

            setup_type_summaries.append(
                SetupTypeSummary(
                    setup_type=setup_type,
                    qualified=group_outcome_stats(type_qualified, research_config.forward_horizons),
                    rejected=group_outcome_stats(type_rejected, research_config.forward_horizons),
                    qualification_lift=qualification_lift(
                        type_qualified, type_rejected, research_config.forward_horizons
                    ),
                    rejection_value=rejection_value(type_rejected, type_qualified, research_config),
                    baseline=baseline,
                )
            )

        summary = ResearchRunSummary(
            run_id=run_id,
            symbol=symbol,
            timeframe=timeframe.value,
            start_date=start_date,
            end_date=end_date,
            bars_processed=replay_result.bars_processed,
            qualified_count=len(qualified),
            rejected_count=len(rejected),
            runtime_seconds=replay_result.runtime_seconds,
            setup_types=setup_type_summaries,
        )

        repository.store_completed_run(
            run_id,
            ledger_entries=entries,
            bars_processed=replay_result.bars_processed,
            qualified_count=len(qualified),
            rejected_count=len(rejected),
            runtime_seconds=replay_result.runtime_seconds,
            summary=summary,
        )
        return run_id
    except Exception as exc:
        repository.fail_run(run_id, str(exc))
        raise


def _build_baseline(
    type_qualified, primary_candles, baseline_samples, research_config
) -> BaselineComparison | None:
    if not type_qualified:
        return None
    dominant_direction = Counter(e.direction for e in type_qualified).most_common(1)[0][0]

    unconditional = compute_unconditional_baseline(
        primary_candles, research_config.forward_horizons, research_config.min_baseline_bucket_size
    )
    regime_matched = compute_regime_matched_baseline(
        primary_candles,
        baseline_samples,
        dominant_direction,
        research_config.forward_horizons,
        research_config.min_baseline_bucket_size,
    )
    return BaselineComparison(
        unconditional=unconditional, regime_matched=regime_matched, regime_label=dominant_direction
    )
