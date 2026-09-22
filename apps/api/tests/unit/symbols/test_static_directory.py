"""(#3) StaticSymbolDirectory search/ranking, and (#4) exact-ticker lookup
for invalid-symbol validation."""

from app.symbols.schemas import AssetType
from app.symbols.static_directory import StaticSymbolDirectory


def test_exact_ticker_match_is_tier_one():
    directory = StaticSymbolDirectory()
    results = directory.search("NVDA")
    assert results[0].ticker == "NVDA"
    assert results[0].match_tier == 1


def test_ticker_prefix_matches():
    directory = StaticSymbolDirectory()
    results = directory.search("NV")
    tickers = [r.ticker for r in results]
    assert "NVDA" in tickers
    assert results[[r.ticker for r in results].index("NVDA")].match_tier == 2


def test_company_name_search_finds_the_right_ticker():
    """The explicit example from the spec: typing 'NVIDIA' must surface NVDA."""
    directory = StaticSymbolDirectory()
    results = directory.search("NVIDIA")
    assert any(r.ticker == "NVDA" for r in results)


def test_company_name_prefix_ranks_above_contains():
    directory = StaticSymbolDirectory()
    # "American" is a prefix match for American Express's name.
    results = directory.search("American")
    assert results[0].ticker == "AXP"
    assert results[0].match_tier == 3


def test_exact_ticker_ranks_above_ticker_prefix():
    directory = StaticSymbolDirectory()
    results = directory.search("V")
    tickers = [r.ticker for r in results]
    assert tickers[0] == "V"  # exact ticker match (Visa) beats prefix matches


def test_watchlist_membership_breaks_ties_within_the_same_tier():
    directory = StaticSymbolDirectory()
    # Several tier-2 ticker-prefix matches for "M"; watchlist membership
    # should reorder MDT ahead of its same-tier peers without changing
    # whether anything else matched.
    boosted = directory.search("M", watchlist_tickers=["MDT"], limit=50)
    boosted_tickers = [r.ticker for r in boosted if r.match_tier == 2]
    unboosted = directory.search("M", limit=50)
    unboosted_tickers = [r.ticker for r in unboosted if r.match_tier == 2]
    assert boosted_tickers.index("MDT") < unboosted_tickers.index("MDT")


def test_empty_query_returns_no_results():
    directory = StaticSymbolDirectory()
    assert directory.search("") == []
    assert directory.search("   ") == []


def test_gibberish_query_returns_no_results():
    """(#4) 'XYZNOTREAL' must never fuzzy-match to something real."""
    directory = StaticSymbolDirectory()
    assert directory.search("XYZNOTREAL") == []


def test_get_returns_none_for_unknown_ticker():
    directory = StaticSymbolDirectory()
    assert directory.get("XYZNOTREAL") is None


def test_get_returns_exact_match_for_known_ticker():
    directory = StaticSymbolDirectory()
    match = directory.get("spy")  # case-insensitive
    assert match is not None
    assert match.ticker == "SPY"
    assert match.asset_type == AssetType.ETF


def test_results_are_bounded_by_limit():
    directory = StaticSymbolDirectory()
    results = directory.search("a", limit=3)
    assert len(results) <= 3
