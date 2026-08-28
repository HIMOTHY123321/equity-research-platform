from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.market_data.candle_cache import REVISION_WINDOW_DAYS, SqlAlchemyCandleCacheRepository
from app.schemas.market_data import Candle, Timeframe

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
OLD_START = NOW - timedelta(days=30)
OLD_END = NOW - timedelta(days=REVISION_WINDOW_DAYS + 1)  # safely outside the revision window
RECENT_END = NOW - timedelta(days=1)  # inside the revision window


def _repo(now=NOW):
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    return SqlAlchemyCandleCacheRepository(session, now=now)


def _candle(timestamp, close=100.0):
    return Candle(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000.0,
    )


def _key(**overrides):
    kwargs = dict(
        provider="yfinance",
        symbol="SPY",
        timeframe="1h",
        requested_start=OLD_START,
        requested_end=OLD_END,
        adjustment_mode="unadjusted",
        session_settings="regular_and_extended (prepost=True)",
    )
    kwargs.update(overrides)
    return kwargs


def test_cache_miss_when_nothing_stored():
    repo = _repo()
    assert repo.get(**_key()) is None


def test_cache_put_then_get_round_trips_candles():
    repo = _repo()
    candles = [_candle(OLD_START + timedelta(hours=i)) for i in range(3)]
    repo.put(**_key(), candles=candles)
    result = repo.get(**_key())
    assert result is not None
    assert [c.timestamp for c in result] == [c.timestamp for c in candles]
    assert [c.close for c in result] == [c.close for c in candles]


def test_cache_miss_on_a_different_range_never_substitutes_a_stored_entry():
    repo = _repo()
    candles = [_candle(OLD_START + timedelta(hours=i)) for i in range(3)]
    repo.put(**_key(), candles=candles)
    different_end = OLD_END - timedelta(days=1)
    assert repo.get(**_key(requested_end=different_end)) is None


def test_cache_miss_on_different_adjustment_mode_or_session_settings():
    repo = _repo()
    candles = [_candle(OLD_START)]
    repo.put(**_key(), candles=candles)
    assert repo.get(**_key(adjustment_mode="split_adjusted")) is None
    assert repo.get(**_key(session_settings="regular_only")) is None


def test_recent_range_is_never_cached_or_served_never_silently_stale():
    repo = _repo()
    candles = [_candle(RECENT_END - timedelta(hours=i)) for i in range(3)]
    repo.put(**_key(requested_end=RECENT_END), candles=candles)
    # put() was a silent no-op for a still-revisable range -- confirm nothing landed.
    assert repo.get(**_key(requested_end=RECENT_END)) is None


def test_existing_settled_entry_is_never_overwritten():
    repo = _repo()
    original = [_candle(OLD_START, close=100.0)]
    repo.put(**_key(), candles=original)
    different = [_candle(OLD_START, close=999.0)]
    repo.put(**_key(), candles=different)  # should be a no-op, not an overwrite
    result = repo.get(**_key())
    assert result[0].close == 100.0


def test_freeze_and_get_frozen_round_trips_regardless_of_recency():
    repo = _repo()
    candles = [_candle(RECENT_END - timedelta(hours=i)) for i in range(3)]
    freeze_id = repo.freeze(
        label="test freeze",
        provider="yfinance",
        symbol="SPY",
        timeframe="1h",
        requested_start=RECENT_END - timedelta(hours=3),
        requested_end=RECENT_END,
        adjustment_mode="unadjusted",
        session_settings="regular_and_extended (prepost=True)",
        candles=candles,
    )
    reloaded = repo.get_frozen(freeze_id)
    assert reloaded is not None
    assert [c.timestamp for c in reloaded] == [c.timestamp for c in candles]


def test_get_frozen_unknown_id_returns_none():
    repo = _repo()
    assert repo.get_frozen("00000000-0000-0000-0000-000000000000") is None
    assert repo.get_frozen("not-a-uuid") is None


def test_list_frozen_datasets_orders_newest_first_and_includes_data_hash():
    import time

    repo = _repo()
    id_a = repo.freeze(
        label="first",
        provider="yfinance",
        symbol="SPY",
        timeframe="1h",
        requested_start=OLD_START,
        requested_end=OLD_END,
        adjustment_mode="unadjusted",
        session_settings="regular_and_extended (prepost=True)",
        candles=[_candle(OLD_START)],
    )
    time.sleep(1.1)  # SQLite server_default now() has 1s resolution
    id_b = repo.freeze(
        label="second",
        provider="yfinance",
        symbol="QQQ",
        timeframe="1h",
        requested_start=OLD_START,
        requested_end=OLD_END,
        adjustment_mode="unadjusted",
        session_settings="regular_and_extended (prepost=True)",
        candles=[_candle(OLD_START)],
    )
    listing = repo.list_frozen_datasets()
    labels = [item["label"] for item in listing]
    assert labels.index("second") < labels.index("first")
    assert {item["freeze_id"] for item in listing} == {id_a, id_b}
    assert all(item["data_hash"] for item in listing)


def test_anti_leakage_frozen_dataset_rerun_produces_identical_setup_ids():
    """Mandatory anti-leakage check (#9): replaying against a frozen
    dataset's candles must produce byte-identical setup ids to replaying
    against the original candles -- freezing (a JSON round-trip through
    the cache/freeze tables) must not perturb anything a deterministic
    setup id is derived from."""
    from app.research.replay import run_replay
    from tests.unit.research.conftest import SYMBOL
    from tests.unit.setup_detection.conftest import load_real_candles

    spy_1h = load_real_candles("SPY_1h")
    spy_1d = load_real_candles("SPY_1d")
    start, end = spy_1h[0].timestamp, spy_1h[-1].timestamp

    original_result = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, start, end, spy_1h, spy_1d, spy_1h, "freeze-original"
    )
    original_ids = sorted(e.setup_id for e in original_result.ledger_entries)

    repo = _repo()
    freeze_id = repo.freeze(
        label="freeze rerun test",
        provider="yfinance",
        symbol=SYMBOL,
        timeframe="1h",
        requested_start=start,
        requested_end=end,
        adjustment_mode="unadjusted",
        session_settings="regular_and_extended (prepost=True)",
        candles=spy_1h,
    )
    frozen_1h = repo.get_frozen(freeze_id)
    freeze_id_daily = repo.freeze(
        label="freeze rerun test daily",
        provider="yfinance",
        symbol=SYMBOL,
        timeframe="1d",
        requested_start=start,
        requested_end=end,
        adjustment_mode="unadjusted",
        session_settings="regular_and_extended (prepost=True)",
        candles=spy_1d,
    )
    frozen_1d = repo.get_frozen(freeze_id_daily)

    frozen_result = run_replay(
        SYMBOL, Timeframe.ONE_HOUR, start, end, frozen_1h, frozen_1d, frozen_1h, "freeze-rerun"
    )
    frozen_ids = sorted(e.setup_id for e in frozen_result.ledger_entries)

    assert frozen_ids == original_ids
    assert len(frozen_ids) > 0


def test_frozen_dataset_data_hash_matches_provenance_convention():
    from app.research.provenance import compute_candle_data_hash

    repo = _repo()
    candles = [_candle(OLD_START + timedelta(hours=i)) for i in range(5)]
    freeze_id = repo.freeze(
        label="hash check",
        provider="yfinance",
        symbol="SPY",
        timeframe="1h",
        requested_start=OLD_START,
        requested_end=OLD_END,
        adjustment_mode="unadjusted",
        session_settings="regular_and_extended (prepost=True)",
        candles=candles,
    )
    listing = repo.list_frozen_datasets()
    row = next(item for item in listing if item["freeze_id"] == freeze_id)
    assert row["data_hash"] == compute_candle_data_hash(candles)
