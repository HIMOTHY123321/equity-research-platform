"""Phase 11.1 (#F): replay <-> canonical pipeline parity. `app.research
.replay.run_replay` already calls the exact same `compute_feature_snapshot`/
`compute_market_structure_snapshot`/`compute_support_resistance_snapshot`/
`compute_setup_detection_snapshot` functions `app.ai_analysis.market_snapshot
.build_market_snapshot` does -- there was never a second implementation.
This proves it empirically: a setup first observed by replay at instant T
must match what the canonical pipeline detects when called directly with
`as_of=T` on the same data -- "semantic identity" (per the spec's own
allowance for this case), not bit-exact float64 equality: two independently
re-fetched candle slices of the same underlying data can legitimately
accumulate float64 noise on the order of 1e-12 relative error in derived
(e.g. moving-average-based) fields without that being a real divergence.
Every value is rounded to 6 decimal places (far finer than any real price
precision) before comparison, which still catches a genuine value
difference while ignoring float64 noise.
"""

from __future__ import annotations

from app.ai_analysis.market_snapshot import build_market_snapshot
from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.replay import run_replay
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1D, SPY_1H, FakeMarketDataProvider


def _round_floats(value, ndigits=6):
    if isinstance(value, float):
        return round(value, ndigits)
    if isinstance(value, dict):
        return {k: _round_floats(v, ndigits) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v, ndigits) for v in value]
    return value


def _find(setup_snapshot, setup_id):
    for pool in (
        setup_snapshot.qualified_setups,
        setup_snapshot.candidates,
        setup_snapshot.rejected_candidates,
        setup_snapshot.recently_invalidated,
        setup_snapshot.recently_expired,
    ):
        for candidate in pool:
            if candidate.id == setup_id:
                return candidate
    return None


def test_replay_first_detection_matches_canonical_pipeline_at_the_same_as_of():
    result = run_replay(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        start_date=SPY_1H[0].timestamp,
        end_date=SPY_1H[-1].timestamp,
        candles=SPY_1H,
        daily_candles=SPY_1D,
        four_hour_candles=SPY_1H,
        research_run_id="00000000-0000-0000-0000-000000000000",
        research_config=DEFAULT_RESEARCH_CONFIG,
    )
    assert result.ledger_entries, "replay must have detected at least one candidate to test parity"

    provider = FakeMarketDataProvider()
    checked = 0
    for entry in result.ledger_entries[:10]:  # a representative sample, not every entry
        canonical = build_market_snapshot(
            "SPY", Timeframe.ONE_HOUR, provider, entry.first_seen_at, now=SPY_1H[-1].timestamp
        )
        found = _find(canonical.setup_snapshot, entry.setup_id)
        assert found is not None, (
            f"canonical pipeline did not detect {entry.setup_id} at {entry.first_seen_at}"
        )
        assert _round_floats(found.model_dump()) == _round_floats(entry.detection.model_dump())
        checked += 1

    assert checked > 0
