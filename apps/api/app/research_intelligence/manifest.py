"""Dataset manifest (#4): full reproducibility record for a multi-symbol
research pull. Reuses Phase 7's per-symbol `DatasetProvenance`
(`app/research/provenance.py`) rather than re-implementing candle hashing --
this module only aggregates provenance across a `ResearchUniverse` and adds
the run-level facts provenance alone doesn't carry (config hash, app
version, adjustment/session settings, a manifest id).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.research.provenance import build_dataset_provenance
from app.research_intelligence.config import APP_VERSION
from app.research_intelligence.schemas import DatasetManifest, ResearchUniverse
from app.schemas.market_data import Candle


def build_dataset_manifest(
    universe: ResearchUniverse,
    provider: str,
    requested_start: datetime,
    requested_end: datetime,
    candles_by_symbol: dict[str, list[Candle]],
    config_hash: str,
    adjustment_mode: str = "unadjusted",
    session_settings: str = "regular_and_extended (prepost=True)",
) -> DatasetManifest:
    """`candles_by_symbol` must have exactly one entry per symbol in
    `universe.symbols` -- a missing symbol means that symbol's pull failed
    or was skipped, and this manifest must not silently paper over that by
    omitting it (#4: never silently shorten what was actually requested)."""
    missing = set(universe.symbols) - set(candles_by_symbol)
    if missing:
        raise ValueError(
            f"dataset manifest is missing candles for requested symbol(s): {sorted(missing)} -- "
            "a failed/skipped pull must be represented explicitly, not silently dropped"
        )

    per_symbol_bar_counts: dict[str, int] = {}
    per_symbol_actual_start: dict[str, Optional[datetime]] = {}
    per_symbol_actual_end: dict[str, Optional[datetime]] = {}
    per_symbol_data_hash: dict[str, str] = {}

    for symbol in universe.symbols:
        candles = candles_by_symbol[symbol]
        provenance = build_dataset_provenance(
            provider, symbol, universe.timeframe, requested_start, requested_end, candles
        )
        per_symbol_bar_counts[symbol] = provenance.candle_count
        per_symbol_actual_start[symbol] = provenance.earliest_candle
        per_symbol_actual_end[symbol] = provenance.latest_candle
        per_symbol_data_hash[symbol] = provenance.data_hash

    return DatasetManifest(
        manifest_id=str(uuid.uuid4()),
        provider=provider,
        symbols=universe.symbols,
        timeframe=universe.timeframe,
        requested_start=requested_start,
        requested_end=requested_end,
        date_selection_rule=universe.date_selection_rule,
        per_symbol_bar_counts=per_symbol_bar_counts,
        per_symbol_actual_start=per_symbol_actual_start,
        per_symbol_actual_end=per_symbol_actual_end,
        per_symbol_data_hash=per_symbol_data_hash,
        config_hash=config_hash,
        app_version=APP_VERSION,
        adjustment_mode=adjustment_mode,
        session_settings=session_settings,
        created_at=datetime.now(timezone.utc),
    )
