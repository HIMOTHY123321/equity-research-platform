"""Deterministic catalyst relevance/significance classification (#14). Same
no-LLM, keyword/category-rule convention as app.news.classification -- this
is a SEPARATE dimension from `CatalystCategory`: a background article can be
correctly categorized (or legitimately UNKNOWN) while still needing to be
flagged as non-causal commentary rather than a genuine, discrete,
market-moving event. Headline phrasing is checked first and wins regardless
of category, since a "$X pays $Y a month" framing is background/general-
investing advice even when it happens to be about a company that also has
real earnings/regulatory news elsewhere.
"""

from __future__ import annotations

from app.news.schemas import CatalystCategory, CatalystRelevance

_PRIMARY_CATEGORIES = frozenset(
    {
        CatalystCategory.EARNINGS,
        CatalystCategory.EARNINGS_PREANNOUNCEMENT,
        CatalystCategory.GUIDANCE,
        CatalystCategory.MERGER_ACQUISITION,
        CatalystCategory.REGULATORY,
        CatalystCategory.LEGAL_LAWSUIT,
        CatalystCategory.FEDERAL_RESERVE,
        CatalystCategory.INTEREST_RATES,
        CatalystCategory.INFLATION,
        CatalystCategory.EMPLOYMENT,
        CatalystCategory.MACROECONOMIC,
        CatalystCategory.GEOPOLITICAL,
        CatalystCategory.PRODUCT_ISSUE,
        CatalystCategory.FINANCING_CAPITAL_RAISE,
    }
)

# General investing/advice/commentary framing -- never a discrete,
# attributable market-moving event for the symbol it happens to mention.
# Deliberately hand-maintained and small, same convention as
# app.news.classification's keyword lists.
_BACKGROUND_PHRASES = (
    "should you buy",
    "should you sell",
    "is it a buy",
    "better buy",
    "top stocks",
    "stocks to buy",
    "stocks to own",
    "passive income",
    "dividend income",
    "before you buy",
    "million in",
    "a month in",
    "pays $",
    " irs ",
    "here's why",
    "here is why",
    "retire",
    "401(k)",
    "401k",
    " ira ",
    "buy now",
    "clear answer",
    "worth about",
    "if the stock doubles",
)


def classify_relevance(category: CatalystCategory, headline: str) -> CatalystRelevance:
    lowered = f" {headline.lower()} "
    if any(phrase in lowered for phrase in _BACKGROUND_PHRASES):
        return CatalystRelevance.BACKGROUND
    if category in _PRIMARY_CATEGORIES:
        return CatalystRelevance.PRIMARY
    return CatalystRelevance.UNKNOWN
