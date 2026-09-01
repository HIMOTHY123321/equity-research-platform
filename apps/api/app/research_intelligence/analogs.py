"""Historical Analog Engine (#25-#28). Deterministic similarity search over
detection-time-only information -- no LLM, no future outcomes anywhere near
the ranking. Architecture is split into three strictly separate stages,
matching the anti-leakage requirement:

1. `extract_features` -- SetupCandidate (+ the detection candle's own
   close) -> AnalogFeatures. Nothing here ever looks past
   `candidate_candle_timestamp`.
2. `distance_between` / `rank_analogs` -- AnalogFeatures pairs -> a
   transparent, itemized distance. Never touches SetupOutcome.
3. `attach_outcomes` -- a separate pass, run strictly after ranking, that
   decorates already-ranked results with their historical outcomes. Mutating
   this pass can never change what stage 2 already decided.
"""

from __future__ import annotations

from typing import Optional

from app.news.schemas import SetupCatalystContext
from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.cohorts import time_since_catalyst_bucket
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.episodes import SetupEpisode
from app.research_intelligence.schemas import (
    AnalogDistance,
    AnalogDiversityReport,
    AnalogFeatures,
    AnalogOutcomeSummary,
    AnalogResult,
    DimensionDistanceEntry,
)
from app.schemas.market_data import Candle
from app.setup_detection.schemas import SetupCandidate

_CATEGORICAL_DIMENSIONS = (
    "setup_type",
    "direction",
    "daily_structure",
    "four_hour_structure",
    "one_hour_structure",
    "rvol_bucket",
    "gap_state",
    # Phase 10 (#I) -- None on both sides unless a caller opts in; see
    # AnalogFeatures' docstring on these two fields.
    "catalyst_category",
    "catalyst_recency_bucket",
)
_NUMERIC_DIMENSIONS = (
    "resistance_confluence",
    "support_confluence",
    "distance_to_support_percent",
    "distance_to_resistance_percent",
    "ma20_relative_percent",
    "range_position",
)

# Fraction of a numeric dimension's normalization scale below which the two
# values are reported as "matched" rather than "differing" in the
# human-readable breakdown -- the exact contribution is always reported
# regardless, this threshold only affects the summary lists.
_NUMERIC_MATCH_FRACTION = 0.1


def detection_close_for(
    candidate: SetupCandidate, candles_by_symbol: dict[str, list[Candle]]
) -> Optional[float]:
    candles = candles_by_symbol.get(candidate.symbol)
    if not candles:
        return None
    detection_candle = next((c for c in candles if c.timestamp == candidate.candidate_candle_timestamp), None)
    return detection_candle.close if detection_candle else None


def extract_features(
    candidate: SetupCandidate,
    detection_close: Optional[float],
    catalyst_context: Optional[SetupCatalystContext] = None,
) -> AnalogFeatures:
    """`catalyst_context` (#I) is optional and defaults to `None`, which
    leaves `catalyst_category`/`catalyst_recency_bucket` both `None` --
    identical output to before this phase existed. Only ever built from
    information already known as of `candidate.candidate_candle_timestamp`
    (app.news.setup_linking's own as_of discipline), so populating it never
    lets future outcome data influence analog ranking (#I "future outcome
    data must NEVER influence analog ranking")."""
    fp = candidate.fingerprint
    context = candidate.context

    distance_to_support_percent = None
    distance_to_resistance_percent = None
    ma20_relative_percent = None
    range_position = None

    if detection_close and context is not None:
        if context.nearest_support_price is not None:
            distance_to_support_percent = (
                abs(detection_close - context.nearest_support_price) / detection_close * 100
            )
        if context.nearest_resistance_price is not None:
            distance_to_resistance_percent = (
                abs(detection_close - context.nearest_resistance_price) / detection_close * 100
            )
        if context.ema20 is not None:
            ma20_relative_percent = (detection_close - context.ema20) / detection_close * 100
        if (
            context.active_range_high is not None
            and context.active_range_low is not None
            and context.active_range_high > context.active_range_low
        ):
            range_position = (detection_close - context.active_range_low) / (
                context.active_range_high - context.active_range_low
            )

    return AnalogFeatures(
        setup_type=candidate.setup_type.value,
        direction=candidate.direction.value,
        daily_structure=fp.daily_structure.value if fp and fp.daily_structure else None,
        four_hour_structure=fp.four_hour_structure.value if fp and fp.four_hour_structure else None,
        one_hour_structure=fp.one_hour_structure.value if fp and fp.one_hour_structure else None,
        rvol_bucket=fp.rvol_bucket if fp else None,
        gap_state=fp.gap_state if fp else None,
        resistance_confluence=float(fp.resistance_confluence) if fp else None,
        support_confluence=float(fp.support_confluence) if fp else None,
        distance_to_support_percent=distance_to_support_percent,
        distance_to_resistance_percent=distance_to_resistance_percent,
        ma20_relative_percent=ma20_relative_percent,
        range_position=range_position,
        catalyst_category=(
            catalyst_context.nearest_catalyst.category.value
            if catalyst_context and catalyst_context.nearest_catalyst
            else None
        ),
        catalyst_recency_bucket=(
            time_since_catalyst_bucket(catalyst_context.nearest_catalyst.hours_before_setup)
            if catalyst_context and catalyst_context.nearest_catalyst
            else None
        ),
    )


def _numeric_scale(dimension: str, config: ResearchIntelligenceConfig) -> float:
    if dimension in ("resistance_confluence", "support_confluence"):
        return config.analog_confluence_scale
    if dimension == "range_position":
        return config.analog_range_position_scale
    return config.analog_percent_distance_scale


def distance_between(
    query: AnalogFeatures,
    candidate: AnalogFeatures,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> AnalogDistance:
    breakdown: list[DimensionDistanceEntry] = []
    matched, differing, missing = [], [], []
    total_contribution = 0.0
    total_weight = 0.0

    for dim in _CATEGORICAL_DIMENSIONS:
        weight = config.analog_weights.get(dim, 0.0)
        a, b = getattr(query, dim), getattr(candidate, dim)
        if a is None or b is None:
            missing.append(dim)
            continue
        is_match = a == b
        contribution = 0.0 if is_match else weight
        (matched if is_match else differing).append(dim)
        total_contribution += contribution
        total_weight += weight
        breakdown.append(
            DimensionDistanceEntry(
                dimension=dim,
                kind="categorical",
                case_value=str(a),
                candidate_value=str(b),
                matched=is_match,
                contribution=contribution,
            )
        )

    for dim in _NUMERIC_DIMENSIONS:
        weight = config.analog_weights.get(dim, 0.0)
        a, b = getattr(query, dim), getattr(candidate, dim)
        if a is None or b is None:
            missing.append(dim)
            continue
        scale = _numeric_scale(dim, config)
        fraction = min(abs(a - b) / scale, 1.0) if scale else 0.0
        contribution = fraction * weight
        is_match = fraction <= _NUMERIC_MATCH_FRACTION
        (matched if is_match else differing).append(dim)
        total_contribution += contribution
        total_weight += weight
        breakdown.append(
            DimensionDistanceEntry(
                dimension=dim,
                kind="numeric",
                case_value=f"{a:.3f}",
                candidate_value=f"{b:.3f}",
                matched=is_match,
                contribution=contribution,
            )
        )

    distance = (total_contribution / total_weight) if total_weight > 0 else 1.0
    return AnalogDistance(
        distance=distance,
        matched_dimensions=matched,
        differing_dimensions=differing,
        missing_dimensions=missing,
        breakdown=breakdown,
    )


def rank_analogs(
    query: AnalogFeatures,
    candidates: list[tuple[SetupLedgerEntry, AnalogFeatures]],
    top_n: Optional[int] = None,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> list[AnalogResult]:
    """Ranking uses ONLY `query`/`candidates`' AnalogFeatures -- no
    SetupOutcome is ever imported or referenced in this function. Ties in
    distance break on setup_id (a stable, deterministic, content-derived
    string) so ranking is reproducible run to run."""
    top_n = top_n if top_n is not None else config.analog_top_n
    scored = [(entry, distance_between(query, features, config)) for entry, features in candidates]
    scored.sort(key=lambda pair: (pair[1].distance, pair[0].setup_id))

    return [
        AnalogResult(
            setup_id=entry.setup_id,
            symbol=entry.symbol,
            timestamp=entry.candidate_candle_timestamp,
            setup_type=entry.setup_type,
            direction=entry.direction,
            distance=distance,
        )
        for entry, distance in scored[:top_n]
    ]


def attach_outcomes(
    results: list[AnalogResult], entries_by_setup_id: dict[str, SetupLedgerEntry]
) -> list[AnalogResult]:
    """Strictly a decoration pass -- takes an already-ranked list and
    returns the same list, same order, with `.outcome` filled in. Never
    reorders, never re-scores."""
    decorated = []
    for result in results:
        entry = entries_by_setup_id.get(result.setup_id)
        outcome = entry.outcome if entry else None
        summary = None
        if outcome is not None:
            horizon_by_bars = {h.horizon_bars: h for h in outcome.horizons if h.available}
            summary = AnalogOutcomeSummary(
                one_bar_directional_return_percent=(
                    horizon_by_bars[1].directional_return_percent if 1 in horizon_by_bars else None
                ),
                five_bar_directional_return_percent=(
                    horizon_by_bars[5].directional_return_percent if 5 in horizon_by_bars else None
                ),
                ten_bar_directional_return_percent=(
                    horizon_by_bars[10].directional_return_percent if 10 in horizon_by_bars else None
                ),
                mfe_atr=outcome.mfe.atr,
                mae_atr=outcome.mae.atr,
            )
        decorated.append(result.model_copy(update={"outcome": summary}))
    return decorated


def analog_diversity_report(
    ranked: list[AnalogResult],
    episode_by_setup_id: dict[str, SetupEpisode],
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> AnalogDiversityReport:
    """(#20) Read-only over an already-ranked list -- never touches
    `distance_between`/`rank_analogs`. Two independent, deterministic
    checks: how many of the top analogs provably share a `SetupEpisode`
    (the strongest "same underlying event" signal this package has), and
    whether one symbol dominates the list."""
    n = len(ranked)
    episode_ids = [
        (episode_by_setup_id[r.setup_id].episode_id if r.setup_id in episode_by_setup_id else None)
        for r in ranked
    ]
    known_episode_ids = [e for e in episode_ids if e is not None]
    without_episode_data = n - len(known_episode_ids)

    episode_counts: dict[str, int] = {}
    for episode_id in known_episode_ids:
        episode_counts[episode_id] = episode_counts.get(episode_id, 0) + 1
    max_same_episode_count = max(episode_counts.values()) if episode_counts else 0

    symbol_counts: dict[str, int] = {}
    for r in ranked:
        symbol_counts[r.symbol] = symbol_counts.get(r.symbol, 0) + 1
    dominant_symbol, dominant_count = (
        max(symbol_counts.items(), key=lambda kv: kv[1]) if symbol_counts else (None, 0)
    )
    dominant_symbol_share = (dominant_count / n) if n else None

    warnings = []
    if max_same_episode_count > 1:
        repeated = sorted(eid for eid, count in episode_counts.items() if count > 1)
        extra = f" (+{len(repeated) - 1} more repeated episodes)" if len(repeated) > 1 else ""
        warnings.append(
            f"SAME_EPISODE_ANALOGS: {max_same_episode_count} of the top {n} analogs share "
            f"episode {repeated[0]}{extra}"
        )
    if dominant_symbol_share is not None and dominant_symbol_share >= config.concentration_warning_share:
        warnings.append(
            f"SYMBOL_CONCENTRATION: {dominant_symbol_share:.0%} of the top {n} analogs are {dominant_symbol}"
        )

    return AnalogDiversityReport(
        total_analogs=n,
        distinct_episode_count=len(set(known_episode_ids)),
        analogs_without_episode_data=without_episode_data,
        max_same_episode_count=max_same_episode_count,
        distinct_symbol_count=len(symbol_counts),
        dominant_symbol=dominant_symbol,
        dominant_symbol_share=dominant_symbol_share,
        warning=" | ".join(warnings) if warnings else None,
    )


def diverse_analogs(
    ranked: list[AnalogResult],
    episode_by_setup_id: dict[str, SetupEpisode],
    limit: Optional[int] = None,
) -> list[AnalogResult]:
    """(#21) The "DIVERSE ANALOGS" view: the same ranked list, same
    distances, filtered to at most one analog per episode -- since `ranked`
    is already sorted by distance, keeping the first occurrence of each
    episode keeps that episode's closest member. Analogs with no known
    episode are never deduplicated against each other or against anything
    else; only entries that provably share an episode are collapsed. The
    underlying similarity calculation (`distance_between`) is never
    touched."""
    seen_episodes: set[str] = set()
    result: list[AnalogResult] = []
    for r in ranked:
        episode = episode_by_setup_id.get(r.setup_id)
        if episode is not None:
            if episode.episode_id in seen_episodes:
                continue
            seen_episodes.add(episode.episode_id)
        result.append(r)
        if limit is not None and len(result) >= limit:
            break
    return result
