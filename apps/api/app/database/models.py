"""SQLAlchemy ORM models — the single source of truth for the schema.

Table groups mirror the pipeline: market data caching, computed structure/levels,
detected setups, scoring, AI interpretation, predictions + their eventual grading,
reports, and backtesting. See docs/decisions/ for schema rationale.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    """Postgres-only UUID primary key, used by the Phase 1 tables below.
    Do not use this for new tables -- see `_portable_uuid_pk`."""
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _portable_uuid_pk() -> Mapped[uuid.UUID]:
    """Cross-dialect UUID primary key (SQLAlchemy 2.0's `Uuid` type: native
    UUID on Postgres, CHAR(32) hex on SQLite) -- used by the Phase 7 tables
    at the bottom of this file so they work against the local SQLite
    default without requiring Postgres. See docs/decisions/0008 for why the
    Phase 1 tables above are left on the Postgres-only helper instead of
    being retrofitted."""
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")
LEVEL_TYPES = ("support", "resistance")
SETUP_DIRECTIONS = ("long", "short")
BIAS_VALUES = ("bullish", "bearish", "neutral")
PREDICTION_STATUSES = ("pending", "triggered", "invalidated", "expired", "closed")
RUN_TYPES = ("manual", "premarket", "weekly_scan", "daily_review", "weekly_prep", "weekly_performance")
RUN_STATUSES = ("running", "completed", "failed")
BACKTEST_STATUSES = ("pending", "running", "completed", "failed")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    watchlists: Mapped[list["Watchlist"]] = relationship(back_populates="user")


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[uuid.UUID] = _uuid_pk()
    ticker: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    asset_class: Mapped[str] = mapped_column(String(32), default="us_equity")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[Optional[User]] = relationship(back_populates="watchlists")
    symbols: Mapped[list["WatchlistSymbol"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )


class WatchlistSymbol(Base):
    __tablename__ = "watchlist_symbols"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol_id", name="uq_watchlist_symbol"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    watchlist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"))
    symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    watchlist: Mapped[Watchlist] = relationship(back_populates="symbols")
    symbol: Mapped[Symbol] = relationship()


class CandleCache(Base):
    """Normalized OHLCV bars, deduplicated per (symbol, timeframe, timestamp)."""

    __tablename__ = "candles_cache"
    __table_args__ = (UniqueConstraint("symbol_id", "timeframe", "timestamp", name="uq_candle_bar"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), index=True)
    timeframe: Mapped[str] = mapped_column(Enum(*TIMEFRAMES, name="timeframe_enum", native_enum=False))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="alpaca")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MarketSnapshot(Base):
    """Point-in-time computed feature bundle for a symbol (feature-engine output)."""

    __tablename__ = "market_snapshots"

    id: Mapped[uuid.UUID] = _uuid_pk()
    symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    features: Mapped[dict] = mapped_column(JSON)
    structure: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Level(Base):
    """Deterministic support/resistance level."""

    __tablename__ = "levels"

    id: Mapped[uuid.UUID] = _uuid_pk()
    symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), index=True)
    timeframe: Mapped[str] = mapped_column(Enum(*TIMEFRAMES, name="level_timeframe_enum", native_enum=False))
    price: Mapped[float] = mapped_column(Float)
    type: Mapped[str] = mapped_column(Enum(*LEVEL_TYPES, name="level_type_enum", native_enum=False))
    strength: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64))
    touch_count: Mapped[int] = mapped_column(Integer, default=0)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisRun(Base):
    """One execution of the full pipeline (manual or scheduled)."""

    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_type: Mapped[str] = mapped_column(Enum(*RUN_TYPES, name="run_type_enum", native_enum=False))
    status: Mapped[str] = mapped_column(
        Enum(*RUN_STATUSES, name="run_status_enum", native_enum=False), default="running"
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    triggered_by: Mapped[str] = mapped_column(String(64), default="manual")
    market_regime: Mapped[Optional[dict]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(String(2000))


class DetectedSetup(Base):
    """Raw output of a setup detector — structured evidence, not just true/false."""

    __tablename__ = "detected_setups"

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), index=True)
    timeframe: Mapped[str] = mapped_column(Enum(*TIMEFRAMES, name="setup_timeframe_enum", native_enum=False))
    setup_type: Mapped[str] = mapped_column(String(64), index=True)
    detected: Mapped[bool] = mapped_column(Boolean)
    direction: Mapped[Optional[str]] = mapped_column(
        Enum(*SETUP_DIRECTIONS, name="setup_direction_enum", native_enum=False)
    )
    trigger_price: Mapped[Optional[float]] = mapped_column(Float)
    invalidation_price: Mapped[Optional[float]] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIAnalysis(Base):
    """Validated AI interpretation of an already-computed setup. Never a data source."""

    __tablename__ = "ai_analyses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    detected_setup_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("detected_setups.id", ondelete="SET NULL")
    )
    ticker: Mapped[str] = mapped_column(String(16))
    bias: Mapped[str] = mapped_column(Enum(*BIAS_VALUES, name="bias_enum", native_enum=False))
    primary_setup: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(4000))
    supporting_factors: Mapped[list] = mapped_column(JSON)
    risk_factors: Mapped[list] = mapped_column(JSON)
    conditions_required: Mapped[list] = mapped_column(JSON)
    confidence_commentary: Mapped[str] = mapped_column(String(2000))
    avoid_if: Mapped[list] = mapped_column(JSON)
    raw_response: Mapped[dict] = mapped_column(JSON)
    passed_validation: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_notes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Prediction(Base):
    """Every setup the system surfaces, saved for later grading. The core measurement loop."""

    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), index=True)
    detected_setup_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detected_setups.id", ondelete="CASCADE"))
    ai_analysis_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("ai_analyses.id", ondelete="SET NULL")
    )

    setup_type: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(
        Enum(*SETUP_DIRECTIONS, name="prediction_direction_enum", native_enum=False)
    )
    entry: Mapped[float] = mapped_column(Float)
    invalidation: Mapped[float] = mapped_column(Float)
    target_1: Mapped[Optional[float]] = mapped_column(Float)
    target_2: Mapped[Optional[float]] = mapped_column(Float)
    target_3: Mapped[Optional[float]] = mapped_column(Float)
    risk_reward_ratio: Mapped[Optional[float]] = mapped_column(Float)

    score: Mapped[int] = mapped_column(Integer)
    score_breakdown: Mapped[dict] = mapped_column(JSON)

    market_regime: Mapped[Optional[dict]] = mapped_column(JSON)
    feature_snapshot: Mapped[dict] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(
        Enum(*PREDICTION_STATUSES, name="prediction_status_enum", native_enum=False), default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    result: Mapped["Optional[PredictionResult]"] = relationship(
        back_populates="prediction", uselist=False, cascade="all, delete-orphan"
    )


class PredictionResult(Base):
    """Grading of a prediction against real subsequent market data."""

    __tablename__ = "prediction_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    prediction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), unique=True
    )

    entry_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    entry_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    stop_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    stop_hit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    target_1_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    target_2_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    target_3_hit: Mapped[bool] = mapped_column(Boolean, default=False)

    max_favorable_excursion: Mapped[Optional[float]] = mapped_column(Float)
    max_adverse_excursion: Mapped[Optional[float]] = mapped_column(Float)
    result_in_r: Mapped[Optional[float]] = mapped_column(Float)

    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    prediction: Mapped[Prediction] = relationship(back_populates="result")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = _uuid_pk()
    report_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    market_regime: Mapped[Optional[dict]] = mapped_column(JSON)
    content: Mapped[dict] = mapped_column(JSON)


class StrategyDefinition(Base):
    __tablename__ = "strategy_definitions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(2000))
    rules: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Backtest(Base):
    __tablename__ = "backtests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    strategy_definition_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("strategy_definitions.id", ondelete="SET NULL")
    )
    symbol_scope: Mapped[list] = mapped_column(JSON)
    timeframe: Mapped[str] = mapped_column(
        Enum(*TIMEFRAMES, name="backtest_timeframe_enum", native_enum=False)
    )
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    min_score: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        Enum(*BACKTEST_STATUSES, name="backtest_status_enum", native_enum=False), default="pending"
    )
    summary_metrics: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[uuid.UUID] = _uuid_pk()
    backtest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("backtests.id", ondelete="CASCADE"), index=True)
    symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    setup_type: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(
        Enum(*SETUP_DIRECTIONS, name="backtest_trade_direction_enum", native_enum=False)
    )
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[float] = mapped_column(Float)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Optional[float]] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    target_price: Mapped[Optional[float]] = mapped_column(Float)
    result_in_r: Mapped[Optional[float]] = mapped_column(Float)
    max_favorable_excursion: Mapped[Optional[float]] = mapped_column(Float)
    max_adverse_excursion: Mapped[Optional[float]] = mapped_column(Float)
    outcome: Mapped[Optional[str]] = mapped_column(String(32))


# ---------------------------------------------------------------------------
# Phase 7: setup ledger, historical replay, and outcome research.
#
# Deliberately NOT built on DetectedSetup/Prediction/PredictionResult above:
# those model a boolean-detected, scored, entry/target/stop-based world that
# doesn't match what Phase 6 actually built (structured evidence trees, no
# scoring) and that Phase 7 is explicitly forbidden from building (no P&L,
# no win/loss, no targets). See docs/decisions/0008 for the full rationale.
# These tables use the portable `_portable_uuid_pk()` so they work against
# the local SQLite default with no Postgres install required.
# ---------------------------------------------------------------------------


class ResearchRun(Base):
    """One historical replay execution over a symbol/timeframe/date range."""

    __tablename__ = "research_runs"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)

    config_hash: Mapped[str] = mapped_column(String(32), index=True)
    config_snapshot: Mapped[dict] = mapped_column(JSON)
    dataset_provenance: Mapped[dict] = mapped_column(JSON)

    bars_processed: Mapped[Optional[int]] = mapped_column(Integer)
    qualified_count: Mapped[Optional[int]] = mapped_column(Integer)
    rejected_count: Mapped[Optional[int]] = mapped_column(Integer)
    runtime_seconds: Mapped[Optional[float]] = mapped_column(Float)
    error: Mapped[Optional[str]] = mapped_column(String(2000))

    # Computed once, right after replay finishes (while candles/outcomes are
    # still in memory) rather than recomputed on every summary request --
    # see app/research/repository.py.
    summary: Mapped[Optional[dict]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SetupLedgerEntry(Base):
    """One setup candidate observed during a replay run. `detection_snapshot`
    is written once, at first observation, and never overwritten -- it is
    the immutable record of what the system knew at detection time.
    `latest_snapshot`/`current_state` track lifecycle progress observed on
    later replay bars without touching the frozen original."""

    __tablename__ = "setup_ledger_entries"
    __table_args__ = (UniqueConstraint("research_run_id", "setup_id", name="uq_run_setup"),)

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    setup_id: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    setup_type: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(16))

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    candidate_candle_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    detection_snapshot: Mapped[dict] = mapped_column(JSON)

    current_state: Mapped[str] = mapped_column(String(16), index=True)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latest_snapshot: Mapped[dict] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SetupOutcomeRecord(Base):
    """Forward-looking outcome metrics for one ledger entry -- always
    computed from candles strictly after the setup's detection time. See
    app/research/outcomes.py for the calculations this stores."""

    __tablename__ = "setup_outcomes"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    ledger_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("setup_ledger_entries.id", ondelete="CASCADE"), unique=True
    )
    outcome: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchSnapshotRecord(Base):
    """Phase 8 (#34): an immutable record of one research conclusion --
    which run(s), rules, dataset, and query produced it. Never updated in
    place after creation; a changed conclusion is always a new row, so an
    old one stays inspectable even after detector logic changes."""

    __tablename__ = "research_snapshots"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    label: Mapped[str] = mapped_column(String(200))
    research_run_ids: Mapped[list] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(32), index=True)
    dataset_manifest: Mapped[dict] = mapped_column(JSON)
    cohort_definition: Mapped[dict] = mapped_column(JSON)
    filters: Mapped[dict] = mapped_column(JSON)
    statistical_output: Mapped[dict] = mapped_column(JSON)
    warning_flags: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CachedCandleSeriesRecord(Base):
    """Phase 9 (#32-#34): a locally cached candle series for one exact
    (provider, symbol, timeframe, requested_start, requested_end,
    adjustment_mode, session_settings) key -- never a partial/generic
    per-symbol cache. `fetched_at` lets the repository enforce "never
    silently stale": a request whose `requested_end` falls inside the
    still-revisable recent window always bypasses this table entirely
    (app/market_data/candle_cache.py), so a hit here is never served for
    data that could have since changed at the provider."""

    __tablename__ = "cached_candle_series"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "symbol",
            "timeframe",
            "requested_start",
            "requested_end",
            "adjustment_mode",
            "session_settings",
            name="uq_candle_cache_key",
        ),
    )

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    provider: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    requested_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    adjustment_mode: Mapped[str] = mapped_column(String(32))
    session_settings: Mapped[str] = mapped_column(String(64))
    candles: Mapped[list] = mapped_column(JSON)
    data_hash: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FrozenDatasetRecord(Base):
    """Phase 9 (#33): an explicit, permanently-immutable snapshot of a
    candle series, keyed only by its own generated id -- never by the
    request tuple, so it is never invalidated or overwritten by a later
    fetch of the "same" range. Reproducing a past research run exactly
    means replaying against a frozen dataset's candles, not re-fetching."""

    __tablename__ = "frozen_datasets"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    label: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    requested_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    adjustment_mode: Mapped[str] = mapped_column(String(32))
    session_settings: Mapped[str] = mapped_column(String(64))
    candles: Mapped[list] = mapped_column(JSON)
    data_hash: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 10: News/Catalyst Context engine. Same portable-UUID-pk convention as
# every table since Phase 7. `article_id`/`event_id` are the stable,
# content-derived business keys (app.news.normalization/events) that make
# ingestion idempotent -- unique constraints on those, not on the internal
# uuid pk, are what a repository's upsert logic actually keys on. See
# app/news/repository.py and docs/decisions/0013.
# ---------------------------------------------------------------------------


class NewsArticleRecord(Base):
    """One normalized, deduplicated source article (#B). Never mutated after
    insert except for fields a provider might legitimately update on
    re-fetch (received_at); classification is fixed at ingestion time."""

    __tablename__ = "news_articles"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    article_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[Optional[str]] = mapped_column(String(200))
    headline: Mapped[str] = mapped_column(String(500))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    url: Mapped[Optional[str]] = mapped_column(String(1000))
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    raw_category: Mapped[Optional[str]] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(64), index=True)
    classification: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalystEventRecord(Base):
    """A deterministic grouping of one or more `NewsArticleRecord`s (#D).
    `event_id` is a pure function of its member article ids (app.news.events)
    -- re-grouping the same articles always produces the same row, which is
    what makes repository upserts idempotent."""

    __tablename__ = "catalyst_events"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    primary_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    affected_symbols: Mapped[list] = mapped_column(JSON, default=list)
    contributing_article_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_count: Mapped[int] = mapped_column(Integer)
    earliest_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latest_update_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(String(500))
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    # (#13/#14) POST-BROWSER-TEST CORRECTION PASS #2: deterministic
    # relevance classification + anchor-article source/link enrichment.
    relevance: Mapped[str] = mapped_column(String(16), default="unknown")
    primary_source: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    primary_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalystEventArticleRecord(Base):
    """Event <-> article membership (#D, #L) as its own relational mapping,
    alongside (never instead of) `CatalystEventRecord.contributing_article_ids`
    -- every source article behind an event is preserved and independently
    queryable ("which events is this one article part of") without deserializing
    every event's JSON list."""

    __tablename__ = "catalyst_event_articles"
    __table_args__ = (UniqueConstraint("event_id", "article_id", name="uq_event_article"),)

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    article_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalystReactionRecord(Base):
    """A cached market-reaction measurement (#F) for one (event, symbol,
    timeframe) -- reaction is symbol-specific even for a market-wide event,
    so it is never collapsed to one row per event. Recomputing is cheap and
    deterministic (app.news.reaction); this table exists so repeated reads
    (dashboard, timeline, research) don't repeat the computation."""

    __tablename__ = "catalyst_reactions"
    __table_args__ = (
        UniqueConstraint("event_id", "symbol", "timeframe", name="uq_reaction_event_symbol_timeframe"),
    )

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    reaction: Mapped[dict] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 11: AI Research Analyst. `EvidencePacketRecord` and
# `ResearchBriefRecord` are immutable snapshots, same convention as
# `ResearchSnapshotRecord` -- a packet/brief is never updated in place; a
# re-generated analysis for the same symbol/setup/as_of is always a new row,
# so an old one stays inspectable (#K "immutable historical snapshots").
# `packet_id`/`brief_id` are the deterministic, content-derived business keys
# (app.ai_analysis.evidence_packet/brief) that make a re-build idempotent --
# same convention as `article_id`/`event_id` in Phase 10.
# ---------------------------------------------------------------------------


class EvidencePacketRecord(Base):
    """One immutable EvidencePacket (#A/#K). The full Pydantic payload is
    stored verbatim as JSON so schema evolution (a new `schema_version`)
    never requires a migration -- only the columns queried on directly
    (symbol/timeframe/as_of/setup_id) are broken out."""

    __tablename__ = "evidence_packets"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    packet_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    schema_version: Mapped[str] = mapped_column(String(16), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    setup_id: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchBriefRecord(Base):
    """One immutable ResearchBrief (#D/#K), always bound to the
    EvidencePacket it was synthesized from via `evidence_packet_id`
    (business key, not a foreign key to the internal uuid pk -- a brief must
    remain inspectable even if the packet row's own lifecycle differs)."""

    __tablename__ = "research_briefs"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    brief_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    evidence_packet_id: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[Optional[str]] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    grounding_rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 12: Forward Prediction Benchmark & Validation Lab. All four tables
# are immutable-snapshot rows, same convention as every table since Phase 7
# -- a forecast/outcome/gate-result is never updated in place; a correction
# is always a new row. `forecast_id`/`outcome_id` are deterministic
# content-derived business keys (idempotent creation, same convention as
# `article_id`/`packet_id`); the repository additionally refuses to ever
# UPDATE an existing forecast row (#F "forecast cannot be edited").
# ---------------------------------------------------------------------------


class ForwardForecastRecord(Base):
    """One immutable, locked forecast (#F). `payload` is the full
    ForwardForecast Pydantic dump; the columns below are only what's
    queried on directly for ledger/performance breakdowns."""

    __tablename__ = "forward_forecasts"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    forecast_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    schema_version: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    market_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    forecast_category: Mapped[str] = mapped_column(String(32), index=True)
    forecast_value: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    forecast_horizon_bars: Mapped[int] = mapped_column(Integer)
    evidence_packet_id: Mapped[str] = mapped_column(String(64), index=True)
    origin: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    run_mode: Mapped[str] = mapped_column(String(16), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    row_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForecastOutcomeRecord(Base):
    """One immutable outcome resolution (#G), linked to its forecast by the
    business key `forecast_id` -- never a mutation of the forecast row."""

    __tablename__ = "forecast_outcomes"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    outcome_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    forecast_id: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    row_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForwardValidationGateVersionRecord(Base):
    """(#P) A versioned, immutable gate-criteria definition. Changing
    criteria always means a new `gate_version` row -- an existing version's
    criteria are never edited, so a past PASS/FAIL decision always stays
    interpretable against the exact rules that produced it."""

    __tablename__ = "forward_validation_gate_versions"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    gate_version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    criteria: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForwardValidationGateResultRecord(Base):
    """(#O/#P) One immutable evaluation run of a gate version against
    whatever forecasts/outcomes existed at `evaluated_at` -- re-running the
    gate later is always a new row, never an overwrite of a past result."""

    __tablename__ = "forward_validation_gate_results"

    id: Mapped[uuid.UUID] = _portable_uuid_pk()
    gate_version: Mapped[str] = mapped_column(String(32), index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    row_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
