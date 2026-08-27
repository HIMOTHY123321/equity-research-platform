import tempfile
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.research_intelligence.snapshots import (
    SnapshotNotFoundError,
    SqlAlchemySnapshotRepository,
    compare_detector_versions,
    compare_snapshots,
)


def _in_memory_repo():
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    return SqlAlchemySnapshotRepository(session)


def _sample_kwargs(**overrides):
    kwargs = dict(
        label="breakout_retest SPY 1H",
        research_run_ids=["run-1", "run-2"],
        config_hash="abc123",
        dataset_manifest={
            "symbols": ["SPY"],
            "timeframe": "1h",
            "requested_start": "2026-01-01T00:00:00Z",
            "requested_end": "2026-08-01T00:00:00Z",
        },
        cohort_definition={"setup_type": "breakout_retest", "direction": "bullish"},
        filters={"rvol_bucket": "1.5-2.0"},
        statistical_output={"median": 0.31, "n": 286},
        warning_flags=["small_sample"],
    )
    kwargs.update(overrides)
    return kwargs


def test_create_and_get_snapshot_round_trips_every_field():
    repo = _in_memory_repo()
    snapshot_id = repo.create_snapshot(**_sample_kwargs())
    snapshot = repo.get_snapshot(snapshot_id)

    assert snapshot.snapshot_id == snapshot_id
    assert snapshot.label == "breakout_retest SPY 1H"
    assert snapshot.research_run_ids == ["run-1", "run-2"]
    assert snapshot.config_hash == "abc123"
    assert snapshot.dataset_manifest["symbols"] == ["SPY"]
    assert snapshot.cohort_definition == {"setup_type": "breakout_retest", "direction": "bullish"}
    assert snapshot.filters == {"rvol_bucket": "1.5-2.0"}
    assert snapshot.statistical_output == {"median": 0.31, "n": 286}
    assert snapshot.warning_flags == ["small_sample"]
    assert snapshot.created_at is not None


def test_get_unknown_snapshot_returns_none():
    repo = _in_memory_repo()
    assert repo.get_snapshot("00000000-0000-0000-0000-000000000000") is None
    assert repo.get_snapshot("not-a-uuid") is None


def test_list_snapshots_orders_newest_first():
    repo = _in_memory_repo()
    id1 = repo.create_snapshot(**_sample_kwargs(label="first"))
    # SQLite's server_default=func.now() has 1-second resolution -- sleep
    # so the two rows get genuinely distinguishable created_at values,
    # otherwise DESC ordering on a tie is not guaranteed to be reverse-
    # insertion-order (this is not a polling wait, just timestamp spacing).
    time.sleep(1.1)
    id2 = repo.create_snapshot(**_sample_kwargs(label="second"))
    snapshots = repo.list_snapshots()
    labels = [s.label for s in snapshots]
    assert labels.index("second") < labels.index("first")
    assert {s.snapshot_id for s in snapshots} == {id1, id2}


def test_snapshot_reload_survives_a_fresh_connection_reopening_the_same_file():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "snapshots.db"
        url = f"sqlite:///{db_path}"

        engine_a = create_engine(url)
        session_a = sessionmaker(bind=engine_a)()
        repo_a = SqlAlchemySnapshotRepository(session_a)
        snapshot_id = repo_a.create_snapshot(**_sample_kwargs())
        session_a.close()
        engine_a.dispose()

        # A brand new engine/session against the same file -- simulates the
        # process restarting entirely, not just a new transaction.
        engine_b = create_engine(url)
        session_b = sessionmaker(bind=engine_b)()
        repo_b = SqlAlchemySnapshotRepository(session_b)
        reloaded = repo_b.get_snapshot(snapshot_id)

        assert reloaded is not None
        assert reloaded.label == "breakout_retest SPY 1H"
        assert reloaded.config_hash == "abc123"


def test_compare_snapshots_same_config_different_dataset_period():
    repo = _in_memory_repo()
    id_a = repo.create_snapshot(**_sample_kwargs(label="jan-jun"))
    id_b = repo.create_snapshot(
        **_sample_kwargs(
            label="jul-dec",
            dataset_manifest={
                "symbols": ["SPY"],
                "timeframe": "1h",
                "requested_start": "2026-07-01T00:00:00Z",
                "requested_end": "2026-12-01T00:00:00Z",
            },
        )
    )
    comparison = compare_snapshots(repo.get_snapshot(id_a), repo.get_snapshot(id_b))
    assert comparison.same_config_hash is True
    assert comparison.same_dataset is False
    changed_fields = {d.field for d in comparison.field_diffs if d.changed}
    assert "dataset_requested_start" in changed_fields
    assert "dataset_requested_end" in changed_fields
    assert "config_hash" not in changed_fields


def test_compare_snapshots_different_config_same_dataset():
    repo = _in_memory_repo()
    id_a = repo.create_snapshot(**_sample_kwargs(config_hash="hash-v1"))
    id_b = repo.create_snapshot(**_sample_kwargs(config_hash="hash-v2"))
    comparison = compare_snapshots(repo.get_snapshot(id_a), repo.get_snapshot(id_b))
    assert comparison.same_config_hash is False
    assert comparison.same_dataset is True


def test_compare_identical_snapshots_has_no_changed_fields():
    repo = _in_memory_repo()
    id_a = repo.create_snapshot(**_sample_kwargs())
    id_b = repo.create_snapshot(**_sample_kwargs())
    comparison = compare_snapshots(repo.get_snapshot(id_a), repo.get_snapshot(id_b))
    assert all(not d.changed for d in comparison.field_diffs)


def test_compare_detector_versions_is_the_same_comparison_as_compare_snapshots():
    """(Phase 9 #17) `compare_detector_versions` is a discoverability alias,
    not a new mechanism -- it must report identically to `compare_snapshots`
    for the same pair of runs (here, two config_hashes on the same dataset,
    i.e. exactly "same data, different detector rules")."""
    repo = _in_memory_repo()
    id_a = repo.create_snapshot(**_sample_kwargs(config_hash="detector-v1"))
    id_b = repo.create_snapshot(**_sample_kwargs(config_hash="detector-v2"))
    snapshot_a, snapshot_b = repo.get_snapshot(id_a), repo.get_snapshot(id_b)

    via_alias = compare_detector_versions(snapshot_a, snapshot_b)
    via_generic = compare_snapshots(snapshot_a, snapshot_b)

    assert via_alias == via_generic
    assert via_alias.same_config_hash is False
    assert via_alias.same_dataset is True


def test_not_found_error_carries_the_requested_id():
    error = SnapshotNotFoundError("missing-id")
    assert error.snapshot_id == "missing-id"
    assert "missing-id" in str(error)
