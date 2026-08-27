from datetime import datetime, timezone

import pytest

from app.research_intelligence.config import APP_VERSION
from app.research_intelligence.manifest import build_dataset_manifest
from app.research_intelligence.universe import build_research_universe
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")


def test_manifest_records_real_per_symbol_bar_counts_and_hashes():
    universe = build_research_universe(("SPY",), "1h")
    manifest = build_dataset_manifest(
        universe,
        provider="yfinance",
        requested_start=SPY_1H[0].timestamp,
        requested_end=SPY_1H[-1].timestamp,
        candles_by_symbol={"SPY": SPY_1H},
        config_hash="fake-config-hash",
    )
    assert manifest.per_symbol_bar_counts["SPY"] == len(SPY_1H)
    assert manifest.per_symbol_actual_start["SPY"] == SPY_1H[0].timestamp
    assert manifest.per_symbol_actual_end["SPY"] == SPY_1H[-1].timestamp
    assert manifest.per_symbol_data_hash["SPY"]  # non-empty, real hash
    assert manifest.app_version == APP_VERSION
    assert manifest.config_hash == "fake-config-hash"


def test_manifest_is_reproducible_deterministic_hash_for_the_same_candles():
    universe = build_research_universe(("SPY",), "1h")
    kwargs = dict(
        provider="yfinance",
        requested_start=SPY_1H[0].timestamp,
        requested_end=SPY_1H[-1].timestamp,
        candles_by_symbol={"SPY": SPY_1H},
        config_hash="fake-config-hash",
    )
    manifest_a = build_dataset_manifest(universe, **kwargs)
    manifest_b = build_dataset_manifest(universe, **kwargs)
    # manifest_id is intentionally unique per build (uuid4), but the data
    # hash -- what actually matters for reproducibility -- must match.
    assert manifest_a.per_symbol_data_hash == manifest_b.per_symbol_data_hash
    assert manifest_a.manifest_id != manifest_b.manifest_id


def test_a_missing_symbols_candles_are_never_silently_dropped():
    universe = build_research_universe(("SPY", "QQQ"), "1h")
    with pytest.raises(ValueError, match="missing candles"):
        build_dataset_manifest(
            universe,
            provider="yfinance",
            requested_start=SPY_1H[0].timestamp,
            requested_end=SPY_1H[-1].timestamp,
            candles_by_symbol={"SPY": SPY_1H},  # QQQ missing entirely
            config_hash="fake-config-hash",
        )


def test_manifest_carries_the_universes_date_selection_rule():
    universe = build_research_universe(("SPY",), "1h")
    manifest = build_dataset_manifest(
        universe,
        provider="yfinance",
        requested_start=SPY_1H[0].timestamp,
        requested_end=SPY_1H[-1].timestamp,
        candles_by_symbol={"SPY": SPY_1H},
        config_hash="fake-config-hash",
    )
    assert manifest.date_selection_rule == universe.date_selection_rule
    assert manifest.symbols == ("SPY",)


def test_created_at_reflects_real_wall_clock_time():
    universe = build_research_universe(("SPY",), "1h")
    before = datetime.now(timezone.utc)
    manifest = build_dataset_manifest(
        universe,
        provider="yfinance",
        requested_start=SPY_1H[0].timestamp,
        requested_end=SPY_1H[-1].timestamp,
        candles_by_symbol={"SPY": SPY_1H},
        config_hash="fake-config-hash",
    )
    after = datetime.now(timezone.utc)
    assert before <= manifest.created_at <= after
