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
    "evidence_packets",
    "research_briefs",
    "forward_forecasts",
    "forecast_outcomes",
    "forward_validation_gate_versions",
    "forward_validation_gate_results",
    "decision_plans",
    "decision_transitions",
    "decision_condition_evaluations",
    "decision_evidence_diff_snapshots",
    "alert_events",
    "alert_acknowledgements",
    "alert_preferences",
    "monitoring_subscriptions",
    "alert_outcomes",
    "alert_horizon_outcomes",
    "signal_gate_versions",
    "signal_gate_results",
    "user_sessions",
    "user_monitoring_subscriptions",
    "user_alert_deliveries",
    "user_alert_preferences",
    "user_push_preferences",
    "long_term_research_snapshots",
    "long_term_scheduled_scan_runs",
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
