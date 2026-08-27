"""Fixed, configurable research universe (#3). The default set of symbols
lives in config, not scattered across engines -- and every call site takes
a `ResearchUniverse` explicitly rather than assuming the default, so a
one-symbol or custom-universe run is never accidentally silently widened
or narrowed to "whatever's convenient."
"""

from __future__ import annotations

from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG, ResearchIntelligenceConfig
from app.research_intelligence.schemas import ResearchUniverse


def default_research_universe(
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> ResearchUniverse:
    return ResearchUniverse(
        symbols=tuple(config.default_universe_symbols),
        timeframe=config.default_universe_timeframe,
        date_selection_rule=config.date_selection_rule,
    )


def build_research_universe(
    symbols: tuple[str, ...],
    timeframe: str,
    config: ResearchIntelligenceConfig = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG,
) -> ResearchUniverse:
    """Build a custom universe. Symbols are normalized (uppercased,
    deduplicated, order-preserved) but never silently dropped, expanded, or
    reordered by anything other than the caller's own request."""
    if not symbols:
        raise ValueError("a research universe must contain at least one symbol")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = raw.strip().upper()
        if not symbol:
            raise ValueError("a research universe symbol cannot be blank")
        if symbol not in seen:
            seen.add(symbol)
            normalized.append(symbol)

    return ResearchUniverse(
        symbols=tuple(normalized),
        timeframe=timeframe,
        date_selection_rule=config.date_selection_rule,
    )
