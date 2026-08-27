"""Independent observation sets (Phase 9 #5-#8). Three ways to look at the
same raw ledger entries, from least to most conservative about counting
dependent observations as separate evidence:

- RAW: every ledger entry (Phase 8's behavior, preserved unchanged).
- EPISODE-LEVEL: one representative entry per `SetupEpisode`
  (`episodes.py::_representative_setup_id` -- first qualified member, else
  first member overall, chosen at detection time, never by outcome).
- PURGED (horizon-specific): a deterministic greedy selection where, once
  an observation is selected, any other observation of the *same symbol*
  whose detection timestamp falls inside the selected observation's own
  forward-outcome window for that horizon is excluded -- the exact
  algorithm the Phase 9 spec describes for "5-bar research." Independence
  is horizon-specific by construction: `purged_sample` takes `horizon_bars`
  as a required argument, there is no single universal "independent" set.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.episodes import SetupEpisode
from app.research_intelligence.schemas import ObservationOverlapDetail, SampleComposition
from app.schemas.market_data import Timeframe
from app.setup_detection.detectors._common import bar_duration_seconds


def episode_level_sample(
    entries: list[SetupLedgerEntry], episodes: list[SetupEpisode]
) -> list[SetupLedgerEntry]:
    entry_by_id = {e.setup_id: e for e in entries}
    representatives = {ep.representative_setup_id for ep in episodes}
    return [entry_by_id[sid] for sid in representatives if sid in entry_by_id]


def purged_sample(
    entries: list[SetupLedgerEntry], horizon_bars: int, timeframe: Timeframe
) -> list[SetupLedgerEntry]:
    """Deterministic, greedy, chronological: process entries earliest
    first; selecting one excludes every later same-symbol entry whose own
    detection timestamp falls within the selected entry's forward-outcome
    window for this horizon. Ties (identical timestamps) break on
    `setup_id` for reproducibility."""
    window = timedelta(seconds=bar_duration_seconds(timeframe) * horizon_bars)
    ordered = sorted(entries, key=lambda e: (e.candidate_candle_timestamp, e.setup_id))

    selected: list[SetupLedgerEntry] = []
    excluded_until: dict[str, Optional[datetime]] = {}  # symbol -> timestamp the next candidate must be after
    for entry in ordered:
        blocked_until = excluded_until.get(entry.symbol)
        if blocked_until is not None and entry.candidate_candle_timestamp <= blocked_until:
            continue
        selected.append(entry)
        window_end = entry.candidate_candle_timestamp + window
        # A later exclusion boundary for the same symbol only ever extends
        # forward -- never shrinks a symbol's blocked window.
        if blocked_until is None or window_end > blocked_until:
            excluded_until[entry.symbol] = window_end
    return selected


def sample_composition(
    entries: list[SetupLedgerEntry],
    episodes: list[SetupEpisode],
    timeframe: Timeframe,
    horizons: tuple = (1, 3, 5, 10, 20),
) -> SampleComposition:
    return SampleComposition(
        raw_count=len(entries),
        episode_count=len(episodes),
        purged_counts_by_horizon={h: len(purged_sample(entries, h, timeframe)) for h in horizons},
    )


def per_observation_overlap(
    entries: list[SetupLedgerEntry],
    horizon_bars: int,
    timeframe: Timeframe,
    episode_by_setup_id: dict,
) -> list[ObservationOverlapDetail]:
    """(#5) Adjacent-pair overlap check (same convention as
    `dependence.py::detect_overlap`), but reported per observation with
    same-symbol/same-episode breakdown and the actual shared-bar count,
    not folded into one aggregate warning."""
    window = timedelta(seconds=bar_duration_seconds(timeframe) * horizon_bars)
    ordered = sorted(entries, key=lambda e: (e.candidate_candle_timestamp, e.setup_id))
    bar_seconds = bar_duration_seconds(timeframe)

    overlaps: dict[str, list[str]] = {e.setup_id: [] for e in ordered}
    shared_bars: dict[str, int] = {e.setup_id: 0 for e in ordered}

    for i in range(len(ordered) - 1):
        current, nxt = ordered[i], ordered[i + 1]
        window_end = current.candidate_candle_timestamp + window
        if nxt.candidate_candle_timestamp < window_end:
            overlaps[current.setup_id].append(nxt.setup_id)
            overlaps[nxt.setup_id].append(current.setup_id)
            shared_seconds = (window_end - nxt.candidate_candle_timestamp).total_seconds()
            shared = max(0, int(shared_seconds // bar_seconds))
            shared_bars[current.setup_id] = max(shared_bars[current.setup_id], shared)
            shared_bars[nxt.setup_id] = max(shared_bars[nxt.setup_id], shared)

    symbol_by_id = {e.setup_id: e.symbol for e in ordered}
    details = []
    for entry in ordered:
        others = overlaps[entry.setup_id]
        same_symbol = sum(1 for sid in others if symbol_by_id.get(sid) == entry.symbol)
        same_episode = sum(
            1
            for sid in others
            if episode_by_setup_id.get(sid) is not None
            and episode_by_setup_id.get(sid) == episode_by_setup_id.get(entry.setup_id)
        )
        details.append(
            ObservationOverlapDetail(
                setup_id=entry.setup_id,
                horizon_bars=horizon_bars,
                overlapping_setup_ids=others,
                overlap_count=len(others),
                same_symbol_overlap_count=same_symbol,
                same_episode_overlap_count=same_episode,
                max_shared_bars=shared_bars[entry.setup_id],
            )
        )
    return details
