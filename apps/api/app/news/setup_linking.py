"""Catalyst <-> setup linking (#G). Produces a small, fixed, descriptive
vocabulary (`SetupCatalystContextLabel`) -- never a bullish/bearish call, a
score, or a recommendation. `build_setup_catalyst_context` only ever reads
`candidate.candidate_candle_timestamp`/`candidate.direction` (both already
frozen at detection time) plus whatever `events`/`reaction_by_event_id` the
caller supplies -- it is the CALLER's responsibility to have already
as_of-filtered those to whatever instant is in effect (#E); this function
performs no fetching and cannot itself introduce lookahead.

Label rule, in explicit priority order (never a judgment call -- mirrors the
"priority order matters, and here is why" convention
app.research_intelligence.evidence_maturity/decay already use):

1. No catalyst event for this symbol falls inside the lookback/lookahead
   window around the setup's detection instant -> NO_RECENT_CATALYST.
2. The nearest catalyst's timestamp is within `timing_ambiguous_window_minutes`
   of the setup's detection instant -> CATALYST_TIMING_AMBIGUOUS (too close
   in time to attribute the setup to the catalyst or vice versa).
3. The nearest catalyst has no usable reaction evidence (no evaluated
   horizon) -> CATALYST_TIMING_AMBIGUOUS (catalyst identified, but there is
   not enough reaction evidence to classify further).
4. Otherwise, the catalyst's first-available-horizon reaction, realigned to
   the SETUP's own direction (positive = same direction as the setup):
   - <= `catalyst_conflicted_threshold_percent` -> CATALYST_CONFLICTED
   - >= `catalyst_supported_threshold_percent` -> CATALYST_SUPPORTED, further
     refined by persistence (latest-available-horizon / first-available-horizon,
     both realigned): <= `reaction_fade_threshold_ratio` -> CATALYST_REACTION_FADED;
     >= `reaction_persist_threshold_ratio` -> CATALYST_REACTION_PERSISTED;
     otherwise stays CATALYST_SUPPORTED (persistence inconclusive).
   - otherwise (between the two thresholds -- a genuinely small/inconclusive
     initial reaction) -> CATALYST_TIMING_AMBIGUOUS (reaction magnitude too
     small to call supported or conflicted).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from app.news.config import DEFAULT_CATALYST_CONFIG, CatalystConfig
from app.news.reaction import measure_market_reaction
from app.news.schemas import (
    CatalystEvent,
    CatalystReference,
    MarketReaction,
    SetupCatalystContext,
    SetupCatalystContextLabel,
)
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupCandidate

if TYPE_CHECKING:
    from app.market_data.provider import MarketDataProvider
    from app.news.provider import NewsProvider
    from app.news.repository import NewsRepository


def _hours_between(later, earlier) -> float:
    return (later - earlier).total_seconds() / 3600.0


def _to_reference(event: CatalystEvent, detection_time) -> CatalystReference:
    gap_hours = _hours_between(detection_time, event.primary_timestamp)
    return CatalystReference(
        event_id=event.event_id,
        category=event.category,
        primary_timestamp=event.primary_timestamp,
        source_count=event.source_count,
        hours_before_setup=gap_hours if gap_hours >= 0 else None,
        hours_after_setup=-gap_hours if gap_hours < 0 else None,
    )


def _aligned_percent(value: Optional[float], candidate: SetupCandidate) -> Optional[float]:
    """Reaction was measured in a neutral, always-bullish-convention
    (app.news.reaction) -- realign it to the setup's own direction so
    "positive" means "agrees with the setup," matching
    app.research.outcomes.directional_delta's sign convention."""
    if value is None:
        return None
    return value if candidate.direction.value == "bullish" else -value


def _first_and_last_available(reaction: MarketReaction):
    available = sorted((h for h in reaction.price_horizons if h.available), key=lambda h: h.horizon_bars)
    if not available:
        return None, None
    return available[0], available[-1]


def build_setup_catalyst_context(
    candidate: SetupCandidate,
    events: list[CatalystEvent],
    reaction_by_event_id: dict[str, MarketReaction],
    config: CatalystConfig = DEFAULT_CATALYST_CONFIG,
) -> SetupCatalystContext:
    detection_time = candidate.candidate_candle_timestamp
    window_start = detection_time - timedelta(hours=config.catalyst_lookback_hours_for_setup_linking)
    window_end = detection_time + timedelta(hours=config.catalyst_lookahead_hours_for_setup_linking)

    relevant = sorted(
        (
            e
            for e in events
            if candidate.symbol in e.affected_symbols and window_start <= e.primary_timestamp <= window_end
        ),
        key=lambda e: e.primary_timestamp,
    )

    if not relevant:
        return SetupCatalystContext(
            setup_id=candidate.id,
            symbol=candidate.symbol,
            label=SetupCatalystContextLabel.NO_RECENT_CATALYST,
            label_basis=(
                f"No catalyst event for {candidate.symbol} within "
                f"{config.catalyst_lookback_hours_for_setup_linking}h before or "
                f"{config.catalyst_lookahead_hours_for_setup_linking}h after detection"
            ),
        )

    before = [_to_reference(e, detection_time) for e in relevant if e.primary_timestamp <= detection_time]
    after = [_to_reference(e, detection_time) for e in relevant if e.primary_timestamp > detection_time]

    nearest_event = min(
        relevant, key=lambda e: (abs(_hours_between(detection_time, e.primary_timestamp)), e.event_id)
    )
    nearest_ref = _to_reference(nearest_event, detection_time)
    gap_hours = _hours_between(detection_time, nearest_event.primary_timestamp)

    if abs(gap_hours * 60) <= config.timing_ambiguous_window_minutes:
        return SetupCatalystContext(
            setup_id=candidate.id,
            symbol=candidate.symbol,
            catalysts_before=before,
            catalysts_after=after,
            nearest_catalyst=nearest_ref,
            label=SetupCatalystContextLabel.CATALYST_TIMING_AMBIGUOUS,
            label_basis=(
                f"Nearest catalyst ({nearest_event.category.value}) is within "
                f"{config.timing_ambiguous_window_minutes} minutes of setup detection -- "
                "too close in time to attribute"
            ),
        )

    reaction = reaction_by_event_id.get(nearest_event.event_id)
    first_horizon, last_horizon = (None, None) if reaction is None else _first_and_last_available(reaction)

    if reaction is None or first_horizon is None:
        return SetupCatalystContext(
            setup_id=candidate.id,
            symbol=candidate.symbol,
            catalysts_before=before,
            catalysts_after=after,
            nearest_catalyst=nearest_ref,
            nearest_reaction=reaction,
            label=SetupCatalystContextLabel.CATALYST_TIMING_AMBIGUOUS,
            label_basis=(
                "Nearest catalyst identified, but no reaction evidence is available yet to classify it"
            ),
        )

    initial_aligned = _aligned_percent(first_horizon.directional_return_percent, candidate)
    last_aligned = _aligned_percent(last_horizon.directional_return_percent, candidate)

    if initial_aligned is not None and initial_aligned <= config.catalyst_conflicted_threshold_percent:
        label = SetupCatalystContextLabel.CATALYST_CONFLICTED
        basis = (
            f"Catalyst reaction at {first_horizon.horizon_bars}-bar horizon moved "
            f"{initial_aligned:.2f}% against the setup's own direction"
        )
    elif initial_aligned is not None and initial_aligned >= config.catalyst_supported_threshold_percent:
        ratio = (
            (last_aligned / initial_aligned) if (last_aligned is not None and initial_aligned != 0) else None
        )
        if ratio is not None and ratio <= config.reaction_fade_threshold_ratio:
            label = SetupCatalystContextLabel.CATALYST_REACTION_FADED
            basis = (
                f"Initial reaction {initial_aligned:.2f}% shrank to {last_aligned:.2f}% "
                f"by the {last_horizon.horizon_bars}-bar horizon (ratio {ratio:.2f})"
            )
        elif ratio is not None and ratio >= config.reaction_persist_threshold_ratio:
            label = SetupCatalystContextLabel.CATALYST_REACTION_PERSISTED
            basis = (
                f"Initial reaction {initial_aligned:.2f}% held to {last_aligned:.2f}% "
                f"by the {last_horizon.horizon_bars}-bar horizon (ratio {ratio:.2f})"
            )
        else:
            label = SetupCatalystContextLabel.CATALYST_SUPPORTED
            basis = f"Initial reaction {initial_aligned:.2f}% agrees with the setup's direction"
    else:
        label = SetupCatalystContextLabel.CATALYST_TIMING_AMBIGUOUS
        val = f"{initial_aligned:.2f}%" if initial_aligned is not None else "unavailable"
        basis = f"Initial reaction ({val}) is too small to call supported or conflicted"

    return SetupCatalystContext(
        setup_id=candidate.id,
        symbol=candidate.symbol,
        catalysts_before=before,
        catalysts_after=after,
        nearest_catalyst=nearest_ref,
        nearest_reaction=reaction,
        label=label,
        label_basis=basis,
    )


def build_setup_catalyst_contexts_batch(
    candidates: list[SetupCandidate],
    news_provider: "NewsProvider",
    market_provider: "MarketDataProvider",
    news_repository: "NewsRepository",
    config: CatalystConfig = DEFAULT_CATALYST_CONFIG,
    candle_limit: int = 50_000,
) -> dict[str, SetupCatalystContext]:
    """Batch entry point shared by the Research Lab catalyst extension
    (app.api.routes.research_catalysts) and the analog engine's optional
    catalyst context (app.research_intelligence.analogs) -- one place that
    fetches/groups catalyst events and computes reactions once per distinct
    symbol (never once per candidate), then calls
    `build_setup_catalyst_context` per candidate exactly as the single-setup
    `/api/catalysts/setup-context` route already does. Keyed by
    `candidate.id` (== a ledger entry's own `setup_id`)."""
    as_of = datetime.now(timezone.utc)
    context_by_id: dict[str, SetupCatalystContext] = {}

    by_symbol: dict[str, list[SetupCandidate]] = {}
    for candidate in candidates:
        by_symbol.setdefault(candidate.symbol, []).append(candidate)

    for symbol, symbol_candidates in by_symbol.items():
        timestamps = [c.candidate_candle_timestamp for c in symbol_candidates]
        start = min(timestamps) - timedelta(hours=config.catalyst_lookback_hours_for_setup_linking)
        end = min(max(timestamps) + timedelta(hours=config.catalyst_lookahead_hours_for_setup_linking), as_of)

        fetched = news_provider.fetch_symbol_news(symbol, start, end, as_of)
        news_repository.upsert_articles(fetched)
        events = news_repository.events_for_symbol_as_of(symbol, start, end, as_of)
        news_repository.persist_events_snapshot(events)

        reaction_by_event_id: dict[str, MarketReaction] = {}
        if events:
            timeframe = Timeframe(symbol_candidates[0].timeframe.value)
            candles = market_provider.get_candles(symbol, timeframe, limit=candle_limit)
            for event in events:
                cached = news_repository.get_reaction(event.event_id, symbol, timeframe.value)
                if cached is not None:
                    reaction_by_event_id[event.event_id] = cached
                    continue
                reaction = measure_market_reaction(event, symbol, timeframe.value, candles, config)
                reaction_by_event_id[event.event_id] = reaction
                if reaction.evaluation_quality is not None and reaction.evaluation_quality.fully_evaluated:
                    news_repository.upsert_reaction(reaction)

        for candidate in symbol_candidates:
            context_by_id[candidate.id] = build_setup_catalyst_context(
                candidate, events, reaction_by_event_id, config
            )

    return context_by_id
