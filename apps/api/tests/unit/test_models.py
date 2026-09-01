from app.database.models import Base

EXPECTED_TABLES = {
    "users",
    "symbols",
    "watchlists",
    "watchlist_symbols",
    "candles_cache",
    "market_snapshots",
    "levels",
    "analysis_runs",
    "detected_setups",
    "ai_analyses",
    "predictions",
    "prediction_results",
    "reports",
    "strategy_definitions",
    "backtests",
    "backtest_trades",
    "research_runs",
    "setup_ledger_entries",
    "setup_outcomes",
    "research_snapshots",
    "cached_candle_series",
    "frozen_datasets",
    "news_articles",
    "catalyst_events",
    "catalyst_event_articles",
    "catalyst_reactions",
}


def test_all_expected_tables_are_registered():
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_candle_uniqueness_constraint_present():
    table = Base.metadata.tables["candles_cache"]
    unique_cols = {
        frozenset(c.name for c in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert frozenset({"symbol_id", "timeframe", "timestamp"}) in unique_cols
