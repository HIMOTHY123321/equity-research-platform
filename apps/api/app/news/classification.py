"""Deterministic catalyst classification (#C). No LLM call anywhere in this
module -- see `ClassificationMethod.DETERMINISTIC_RULE`. Rules are checked
in a fixed priority order (provider-supplied category, then strong keyword
phrases, then weak single-word fallbacks); the first match wins, and an
article matching nothing stays honestly UNKNOWN rather than being force-fit
into a category or given a fabricated confidence score (#M "no fake
confidence").
"""

from __future__ import annotations

from typing import Optional

from app.news.schemas import CatalystCategory, CatalystClassification, ClassificationBasis

# Provider-supplied raw categories that map directly and unambiguously onto
# this taxonomy (#C: "provider-supplied or deterministic mapping, never a
# model call") -- checked before any keyword rule. Deliberately small: most
# providers, including this phase's yfinance dev provider, do not supply a
# usable category at all, so the keyword rules below carry most of the load.
_PROVIDER_CATEGORY_MAP: dict[str, CatalystCategory] = {
    "earnings": CatalystCategory.EARNINGS,
    "press release": CatalystCategory.COMPANY_SPECIFIC_OTHER,
    "press releases": CatalystCategory.COMPANY_SPECIFIC_OTHER,
}

# (category, phrase-tuple) rules, most-specific first -- the first category
# whose phrase appears in the lowercased headline wins. Order matters only
# so a more specific category (e.g. EARNINGS_PREANNOUNCEMENT) is checked
# before a broader one (EARNINGS) that might also match.
_STRONG_KEYWORD_RULES: tuple[tuple[CatalystCategory, tuple[str, ...]], ...] = (
    (
        CatalystCategory.EARNINGS_PREANNOUNCEMENT,
        ("preannounces", "pre-announces", "warns on earnings", "profit warning", "guidance warning"),
    ),
    (
        CatalystCategory.EARNINGS,
        (
            "quarterly results",
            "quarterly earnings",
            "q1 earnings",
            "q2 earnings",
            "q3 earnings",
            "q4 earnings",
            "earnings per share",
            "reports earnings",
            "beats earnings",
            "misses earnings",
            "eps of",
            "fiscal year results",
        ),
    ),
    (
        CatalystCategory.GUIDANCE,
        (
            "raises guidance",
            "cuts guidance",
            "lowers guidance",
            "updates guidance",
            "full-year outlook",
            "fiscal year outlook",
            "narrows guidance",
        ),
    ),
    (
        CatalystCategory.ANALYST_RATING,
        (
            "upgrades",
            "downgrades",
            "initiates coverage",
            "reiterates rating",
            "maintains rating",
            "hikes rating",
        ),
    ),
    (CatalystCategory.PRICE_TARGET, ("price target",)),
    (
        CatalystCategory.MERGER_ACQUISITION,
        (
            "to acquire",
            "acquisition of",
            "merger agreement",
            "agrees to merge",
            "takeover bid",
            "to be acquired",
            "buyout offer",
        ),
    ),
    (
        CatalystCategory.FINANCING_CAPITAL_RAISE,
        (
            "secondary offering",
            "public offering",
            "private placement",
            "capital raise",
            "convertible notes offering",
        ),
    ),
    (CatalystCategory.BUYBACK, ("share buyback", "stock buyback", "repurchase program", "buyback program")),
    (
        CatalystCategory.DIVIDEND,
        ("declares dividend", "quarterly dividend", "special dividend", "dividend increase", "cuts dividend"),
    ),
    (
        CatalystCategory.MANAGEMENT_CHANGE,
        (
            "names new ceo",
            "appoints ceo",
            "ceo resigns",
            "ceo steps down",
            "names new cfo",
            "appoints cfo",
            "cfo resigns",
            "names interim ceo",
        ),
    ),
    (
        CatalystCategory.LEGAL_LAWSUIT,
        (
            "files lawsuit",
            "class action",
            "sec investigation",
            "sec charges",
            "settles lawsuit",
            "antitrust probe",
        ),
    ),
    (
        CatalystCategory.REGULATORY,
        ("fda approval", "fda rejects", "fda approves", "regulatory approval", "ftc probe", "doj probe"),
    ),
    (CatalystCategory.PRODUCT_LAUNCH, ("unveils", "launches new", "announces new product", "product launch")),
    (CatalystCategory.PRODUCT_ISSUE, ("recall", "product recall", "safety issue", "service outage")),
    (CatalystCategory.SUPPLY_CHAIN, ("supply chain", "chip shortage", "supplier issue", "shipping delays")),
    (CatalystCategory.FILING, ("10-k", "10-q", "8-k", "sec filing", "files with the sec")),
    (CatalystCategory.FEDERAL_RESERVE, ("federal reserve", "fomc", "fed chair", "fed rate decision")),
    (CatalystCategory.INTEREST_RATES, ("interest rate", "rate hike", "rate cut", "rate decision")),
    (CatalystCategory.INFLATION, ("cpi report", "inflation data", "consumer price index")),
    (CatalystCategory.EMPLOYMENT, ("jobs report", "nonfarm payrolls", "unemployment rate")),
    (CatalystCategory.GEOPOLITICAL, ("tariff", "sanctions", "trade war", "geopolitical tension")),
    (CatalystCategory.MACROECONOMIC, ("gdp growth", "recession fears", "economic outlook")),
)

_WEAK_KEYWORD_RULES: tuple[tuple[CatalystCategory, tuple[str, ...]], ...] = (
    (CatalystCategory.EARNINGS, ("earnings",)),
    (CatalystCategory.ANALYST_RATING, ("analyst", "rating")),
    (CatalystCategory.SECTOR_INDUSTRY, ("sector", "industry")),
)


def classify_article(headline: str, provider_raw_category: Optional[str]) -> CatalystClassification:
    if provider_raw_category:
        mapped = _PROVIDER_CATEGORY_MAP.get(provider_raw_category.strip().lower())
        if mapped is not None:
            return CatalystClassification(
                category=mapped,
                basis=ClassificationBasis.PROVIDER_CATEGORY_DIRECT_MAP,
                matched_rules=[f"provider_category={provider_raw_category}"],
                provider_raw_category=provider_raw_category,
            )

    lowered = headline.lower()

    for category, phrases in _STRONG_KEYWORD_RULES:
        matched = [p for p in phrases if p in lowered]
        if matched:
            return CatalystClassification(
                category=category,
                basis=ClassificationBasis.STRONG_KEYWORD_MATCH,
                matched_rules=matched,
                provider_raw_category=provider_raw_category,
            )

    for category, phrases in _WEAK_KEYWORD_RULES:
        matched = [p for p in phrases if p in lowered]
        if matched:
            return CatalystClassification(
                category=category,
                basis=ClassificationBasis.WEAK_KEYWORD_FALLBACK,
                matched_rules=matched,
                provider_raw_category=provider_raw_category,
            )

    return CatalystClassification(
        category=CatalystCategory.UNKNOWN,
        basis=ClassificationBasis.UNKNOWN_NO_MATCH,
        matched_rules=[],
        provider_raw_category=provider_raw_category,
    )
