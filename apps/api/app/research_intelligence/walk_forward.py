"""Anchored walk-forward validation (Phase 9 #13-15, mandatory). Splits a
chronologically sorted sample into successive, non-overlapping, contiguous
folds and re-evaluates the same finding on each fold in isolation -- never
shuffled, never re-fit per fold (this codebase tunes nothing: #16), and
every fold's test slice is strictly later than every earlier fold's. The
goal is stability testing, not optimization: does the finding's direction
hold up on genuinely unseen, later time periods, or did the pooled result
depend on one lucky stretch of history?

Rolling walk-forward (a fixed-width training window that slides forward
instead of expanding) is explicitly deferred (#15) -- anchored is the
mandatory form, and correctness on that one form matters more than adding
both.
"""

from __future__ import annotations

from app.research.schemas import SetupLedgerEntry
from app.research.summary import horizon_values
from app.research_intelligence.schemas import StabilityLabel, WalkForwardReport, WalkForwardWindow
from app.research_intelligence.statistics import summarize_distribution


def _chronological_folds(entries: list[SetupLedgerEntry], fold_count: int) -> list[list[SetupLedgerEntry]]:
    """Contiguous, count-based chunks of a chronologically sorted sequence
    -- same "absorb the rounding remainder into the last chunk" convention
    `partitions.py::build_partition_plan` already uses, applied to entries
    instead of candle timestamps."""
    ordered = sorted(entries, key=lambda e: (e.candidate_candle_timestamp, e.setup_id))
    n = len(ordered)
    base = n // fold_count
    folds: list[list[SetupLedgerEntry]] = []
    cursor = 0
    for i in range(fold_count):
        # The last fold absorbs any remainder so every entry is accounted for.
        count = base if i < fold_count - 1 else n - cursor
        folds.append(ordered[cursor : cursor + count])
        cursor += count
    return folds


def anchored_walk_forward(
    entries: list[SetupLedgerEntry],
    horizon_bars: int,
    finding_label: str,
    fold_count: int = 5,
) -> WalkForwardReport:
    """Divides `entries` into `fold_count` + 1 contiguous chronological
    chunks: chunk 0 is the initial anchor history (never itself evaluated
    as a fold), and chunks 1..fold_count are successive test folds. Fold i's
    "train" boundary is the union of chunks 0..i-1 -- it expands with each
    fold, but nothing is fit on it. Folds with too few entries for chunking
    (fewer than 2 * (fold_count + 1)) return an empty window list rather
    than a misleadingly tiny split."""
    ordered = sorted(entries, key=lambda e: (e.candidate_candle_timestamp, e.setup_id))
    if len(ordered) < 2 * (fold_count + 1):
        return WalkForwardReport(
            finding_label=finding_label,
            horizon_bars=horizon_bars,
            windows=[],
            positive_median_window_count=0,
            negative_median_window_count=0,
            stability=StabilityLabel.INSUFFICIENT_DATA,
            stability_basis=f"only {len(ordered)} entries available; need at least {2 * (fold_count + 1)}",
        )

    chunks = _chronological_folds(ordered, fold_count + 1)
    windows: list[WalkForwardWindow] = []
    for i in range(1, fold_count + 1):
        train_chunks = [e for chunk in chunks[:i] for e in chunk]
        test_chunk = chunks[i]
        if not test_chunk:
            continue
        distribution = summarize_distribution(horizon_values(test_chunk, horizon_bars))
        windows.append(
            WalkForwardWindow(
                window_index=i,
                train_start=train_chunks[0].candidate_candle_timestamp,
                train_end=train_chunks[-1].candidate_candle_timestamp,
                test_start=test_chunk[0].candidate_candle_timestamp,
                test_end=test_chunk[-1].candidate_candle_timestamp,
                test_distribution=distribution,
            )
        )

    stability, basis, positive, negative = _classify_walk_forward_stability(windows)
    return WalkForwardReport(
        finding_label=finding_label,
        horizon_bars=horizon_bars,
        windows=windows,
        positive_median_window_count=positive,
        negative_median_window_count=negative,
        stability=stability,
        stability_basis=basis,
    )


def _classify_walk_forward_stability(windows: list[WalkForwardWindow]) -> tuple:
    usable = [w for w in windows if w.test_distribution.median is not None]
    positive = sum(1 for w in usable if w.test_distribution.median > 0)
    negative = sum(1 for w in usable if w.test_distribution.median < 0)

    if len(usable) < 2:
        return (
            StabilityLabel.INSUFFICIENT_DATA,
            "fewer than 2 folds had a usable median",
            positive,
            negative,
        )

    medians = {w.window_index: w.test_distribution.median for w in usable}
    signs = {(m > 0) for m in medians.values() if m != 0}
    if len(signs) > 1:
        return (
            StabilityLabel.UNSTABLE,
            f"median directional return changes sign across folds: {medians}",
            positive,
            negative,
        )
    return (
        StabilityLabel.STABLE,
        f"median directional return keeps the same sign across folds: {medians}",
        positive,
        negative,
    )
