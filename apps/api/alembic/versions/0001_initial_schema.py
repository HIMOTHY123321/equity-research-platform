"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-23

Hand-authored from app.database.models (generated once via SQLAlchemy's DDL
compiler, no live database required to produce this file). Table order
respects foreign-key dependencies.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))

    op.execute(sa.text("""
    CREATE TABLE analysis_runs (
    	id UUID NOT NULL, 
    	run_type VARCHAR(18) NOT NULL, 
    	status VARCHAR(9) NOT NULL, 
    	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	completed_at TIMESTAMP WITH TIME ZONE, 
    	triggered_by VARCHAR(64) NOT NULL, 
    	market_regime JSON, 
    	error VARCHAR(2000), 
    	PRIMARY KEY (id)
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE reports (
    	id UUID NOT NULL, 
    	report_type VARCHAR(32) NOT NULL, 
    	title VARCHAR(255) NOT NULL, 
    	generated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	period_start TIMESTAMP WITH TIME ZONE, 
    	period_end TIMESTAMP WITH TIME ZONE, 
    	market_regime JSON, 
    	content JSON NOT NULL, 
    	PRIMARY KEY (id)
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE strategy_definitions (
    	id UUID NOT NULL, 
    	name VARCHAR(255) NOT NULL, 
    	description VARCHAR(2000), 
    	rules JSON NOT NULL, 
    	is_active BOOLEAN NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id)
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE symbols (
    	id UUID NOT NULL, 
    	ticker VARCHAR(16) NOT NULL, 
    	name VARCHAR(255), 
    	asset_class VARCHAR(32) NOT NULL, 
    	is_active BOOLEAN NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id)
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE users (
    	id UUID NOT NULL, 
    	email VARCHAR(255) NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	UNIQUE (email)
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE backtests (
    	id UUID NOT NULL, 
    	name VARCHAR(255) NOT NULL, 
    	strategy_definition_id UUID, 
    	symbol_scope JSON NOT NULL, 
    	timeframe VARCHAR(3) NOT NULL, 
    	start_date TIMESTAMP WITH TIME ZONE NOT NULL, 
    	end_date TIMESTAMP WITH TIME ZONE NOT NULL, 
    	min_score INTEGER, 
    	status VARCHAR(9) NOT NULL, 
    	summary_metrics JSON, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	FOREIGN KEY(strategy_definition_id) REFERENCES strategy_definitions (id) ON DELETE SET NULL
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE candles_cache (
    	id UUID NOT NULL, 
    	symbol_id UUID NOT NULL, 
    	timeframe VARCHAR(3) NOT NULL, 
    	timestamp TIMESTAMP WITH TIME ZONE NOT NULL, 
    	open FLOAT NOT NULL, 
    	high FLOAT NOT NULL, 
    	low FLOAT NOT NULL, 
    	close FLOAT NOT NULL, 
    	volume FLOAT NOT NULL, 
    	source VARCHAR(32) NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	CONSTRAINT uq_candle_bar UNIQUE (symbol_id, timeframe, timestamp), 
    	FOREIGN KEY(symbol_id) REFERENCES symbols (id) ON DELETE CASCADE
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE detected_setups (
    	id UUID NOT NULL, 
    	analysis_run_id UUID NOT NULL, 
    	symbol_id UUID NOT NULL, 
    	timeframe VARCHAR(3) NOT NULL, 
    	setup_type VARCHAR(64) NOT NULL, 
    	detected BOOLEAN NOT NULL, 
    	direction VARCHAR(5), 
    	trigger_price FLOAT, 
    	invalidation_price FLOAT, 
    	evidence JSON NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE, 
    	FOREIGN KEY(symbol_id) REFERENCES symbols (id) ON DELETE CASCADE
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE levels (
    	id UUID NOT NULL, 
    	symbol_id UUID NOT NULL, 
    	timeframe VARCHAR(3) NOT NULL, 
    	price FLOAT NOT NULL, 
    	type VARCHAR(10) NOT NULL, 
    	strength FLOAT NOT NULL, 
    	source VARCHAR(64) NOT NULL, 
    	touch_count INTEGER NOT NULL, 
    	as_of TIMESTAMP WITH TIME ZONE NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	FOREIGN KEY(symbol_id) REFERENCES symbols (id) ON DELETE CASCADE
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE market_snapshots (
    	id UUID NOT NULL, 
    	symbol_id UUID NOT NULL, 
    	as_of TIMESTAMP WITH TIME ZONE NOT NULL, 
    	features JSON NOT NULL, 
    	structure JSON NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	FOREIGN KEY(symbol_id) REFERENCES symbols (id) ON DELETE CASCADE
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE watchlists (
    	id UUID NOT NULL, 
    	user_id UUID, 
    	name VARCHAR(100) NOT NULL, 
    	is_default BOOLEAN NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE ai_analyses (
    	id UUID NOT NULL, 
    	detected_setup_id UUID, 
    	ticker VARCHAR(16) NOT NULL, 
    	bias VARCHAR(7) NOT NULL, 
    	primary_setup VARCHAR(64) NOT NULL, 
    	summary VARCHAR(4000) NOT NULL, 
    	supporting_factors JSON NOT NULL, 
    	risk_factors JSON NOT NULL, 
    	conditions_required JSON NOT NULL, 
    	confidence_commentary VARCHAR(2000) NOT NULL, 
    	avoid_if JSON NOT NULL, 
    	raw_response JSON NOT NULL, 
    	passed_validation BOOLEAN NOT NULL, 
    	validation_notes JSON NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	FOREIGN KEY(detected_setup_id) REFERENCES detected_setups (id) ON DELETE SET NULL
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE backtest_trades (
    	id UUID NOT NULL, 
    	backtest_id UUID NOT NULL, 
    	symbol_id UUID NOT NULL, 
    	setup_type VARCHAR(64) NOT NULL, 
    	direction VARCHAR(5) NOT NULL, 
    	entry_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    	entry_price FLOAT NOT NULL, 
    	exit_time TIMESTAMP WITH TIME ZONE, 
    	exit_price FLOAT, 
    	stop_price FLOAT NOT NULL, 
    	target_price FLOAT, 
    	result_in_r FLOAT, 
    	max_favorable_excursion FLOAT, 
    	max_adverse_excursion FLOAT, 
    	outcome VARCHAR(32), 
    	PRIMARY KEY (id), 
    	FOREIGN KEY(backtest_id) REFERENCES backtests (id) ON DELETE CASCADE, 
    	FOREIGN KEY(symbol_id) REFERENCES symbols (id) ON DELETE CASCADE
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE watchlist_symbols (
    	id UUID NOT NULL, 
    	watchlist_id UUID NOT NULL, 
    	symbol_id UUID NOT NULL, 
    	added_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	CONSTRAINT uq_watchlist_symbol UNIQUE (watchlist_id, symbol_id), 
    	FOREIGN KEY(watchlist_id) REFERENCES watchlists (id) ON DELETE CASCADE, 
    	FOREIGN KEY(symbol_id) REFERENCES symbols (id) ON DELETE CASCADE
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE predictions (
    	id UUID NOT NULL, 
    	analysis_run_id UUID NOT NULL, 
    	symbol_id UUID NOT NULL, 
    	detected_setup_id UUID NOT NULL, 
    	ai_analysis_id UUID, 
    	setup_type VARCHAR(64) NOT NULL, 
    	direction VARCHAR(5) NOT NULL, 
    	entry FLOAT NOT NULL, 
    	invalidation FLOAT NOT NULL, 
    	target_1 FLOAT, 
    	target_2 FLOAT, 
    	target_3 FLOAT, 
    	risk_reward_ratio FLOAT, 
    	score INTEGER NOT NULL, 
    	score_breakdown JSON NOT NULL, 
    	market_regime JSON, 
    	feature_snapshot JSON NOT NULL, 
    	status VARCHAR(11) NOT NULL, 
    	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE, 
    	FOREIGN KEY(symbol_id) REFERENCES symbols (id) ON DELETE CASCADE, 
    	FOREIGN KEY(detected_setup_id) REFERENCES detected_setups (id) ON DELETE CASCADE, 
    	FOREIGN KEY(ai_analysis_id) REFERENCES ai_analyses (id) ON DELETE SET NULL
    );
    """))

    op.execute(sa.text("""
    CREATE TABLE prediction_results (
    	id UUID NOT NULL, 
    	prediction_id UUID NOT NULL, 
    	entry_triggered BOOLEAN NOT NULL, 
    	entry_triggered_at TIMESTAMP WITH TIME ZONE, 
    	stop_hit BOOLEAN NOT NULL, 
    	stop_hit_at TIMESTAMP WITH TIME ZONE, 
    	target_1_hit BOOLEAN NOT NULL, 
    	target_2_hit BOOLEAN NOT NULL, 
    	target_3_hit BOOLEAN NOT NULL, 
    	max_favorable_excursion FLOAT, 
    	max_adverse_excursion FLOAT, 
    	result_in_r FLOAT, 
    	closed_at TIMESTAMP WITH TIME ZONE, 
    	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    	PRIMARY KEY (id), 
    	UNIQUE (prediction_id), 
    	FOREIGN KEY(prediction_id) REFERENCES predictions (id) ON DELETE CASCADE
    );
    """))


def downgrade() -> None:
    op.execute(sa.text("""
    DROP TABLE IF EXISTS "prediction_results" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "predictions" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "watchlist_symbols" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "backtest_trades" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "ai_analyses" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "watchlists" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "market_snapshots" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "levels" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "detected_setups" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "candles_cache" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "backtests" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "users" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "symbols" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "strategy_definitions" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "reports" CASCADE;
    """))

    op.execute(sa.text("""
    DROP TABLE IF EXISTS "analysis_runs" CASCADE;
    """))

