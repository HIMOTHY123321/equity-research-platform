"""(#14) Deterministic catalyst relevance classification -- a separate
dimension from category, proving background/general-investing articles
never read as primary market-moving catalysts regardless of what category
they happen to match."""

from app.news.relevance import classify_relevance
from app.news.schemas import CatalystCategory, CatalystRelevance


def test_earnings_category_is_primary():
    result = classify_relevance(CatalystCategory.EARNINGS, "Acme reports quarterly earnings beat")
    assert result == CatalystRelevance.PRIMARY


def test_regulatory_category_is_primary():
    result = classify_relevance(CatalystCategory.REGULATORY, "FDA approves Acme's new drug")
    assert result == CatalystRelevance.PRIMARY


def test_browser_confirmed_background_article_is_not_primary():
    """The exact real headline the user's browser test flagged: a general
    investing/tax article that must never read as a causal SPY catalyst."""
    headline = (
        "$1 Million in VOO Pays $871 a Month, and Covering the Gap Means "
        "Selling Shares the IRS Taxes"
    )
    result = classify_relevance(CatalystCategory.UNKNOWN, headline)
    assert result == CatalystRelevance.BACKGROUND


def test_should_you_buy_headline_is_background_even_with_primary_category():
    """Headline phrasing wins over category -- a weak-keyword-matched
    category must not launder background commentary into PRIMARY."""
    result = classify_relevance(
        CatalystCategory.ANALYST_RATING, "Should You Buy Costco Stock Before Sept. 24?"
    )
    assert result == CatalystRelevance.BACKGROUND


def test_unknown_category_with_no_background_signal_stays_unknown():
    result = classify_relevance(CatalystCategory.UNKNOWN, "Company mentioned in passing")
    assert result == CatalystRelevance.UNKNOWN


def test_sector_industry_category_with_no_signal_stays_unknown():
    """Not every non-primary category is background -- an honestly
    unclassifiable case stays UNKNOWN rather than being force-fit either
    way."""
    result = classify_relevance(CatalystCategory.SECTOR_INDUSTRY, "Semiconductor sector update")
    assert result == CatalystRelevance.UNKNOWN
