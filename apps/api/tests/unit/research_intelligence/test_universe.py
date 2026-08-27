import pytest

from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
from app.research_intelligence.universe import build_research_universe, default_research_universe


def test_default_universe_matches_config_not_a_hardcoded_list():
    universe = default_research_universe()
    assert universe.symbols == DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.default_universe_symbols
    assert universe.timeframe == DEFAULT_RESEARCH_INTELLIGENCE_CONFIG.default_universe_timeframe


def test_custom_universe_normalizes_case_and_dedupes_without_reordering():
    universe = build_research_universe(("spy", "SPY", "qqq"), "1d")
    assert universe.symbols == ("SPY", "QQQ")


def test_custom_universe_uses_the_same_date_selection_rule_as_default():
    custom = build_research_universe(("NVDA",), "1h")
    default = default_research_universe()
    assert custom.date_selection_rule == default.date_selection_rule


def test_empty_universe_is_rejected():
    with pytest.raises(ValueError, match="at least one symbol"):
        build_research_universe((), "1h")


def test_blank_symbol_is_rejected():
    with pytest.raises(ValueError, match="cannot be blank"):
        build_research_universe(("SPY", "  "), "1h")
