"""Phase 16 (§8/§28/§29): `worker_mode` gates whether app.main's lifespan
starts background monitors -- "combined"/"worker" start them, "api" does
not (so a multi-replica web deployment never runs a duplicate copy of any
global monitor per replica). Also a basic import/construction smoke test
for the standalone app.worker entrypoint."""

from __future__ import annotations

import inspect

from app.config import Settings


def test_worker_mode_defaults_to_combined():
    assert Settings(_env_file=None).worker_mode == "combined"


def test_worker_mode_accepts_api_and_worker():
    assert Settings(_env_file=None, worker_mode="api").worker_mode == "api"
    assert Settings(_env_file=None, worker_mode="worker").worker_mode == "worker"


def test_runs_background_workers_is_false_only_in_api_mode():
    # §8/§28/§29/§121: exactly the predicate app.main.lifespan gates
    # starting the global monitors on -- "api" mode (a web replica behind
    # a load balancer) must never also run a duplicate copy of every
    # global background scan.
    assert Settings(_env_file=None, worker_mode="combined").runs_background_workers is True
    assert Settings(_env_file=None, worker_mode="worker").runs_background_workers is True
    assert Settings(_env_file=None, worker_mode="api").runs_background_workers is False


def test_worker_module_exposes_an_async_run_worker_entrypoint():
    import app.worker as worker_module

    assert inspect.iscoroutinefunction(worker_module.run_worker)
    assert callable(worker_module.main)
