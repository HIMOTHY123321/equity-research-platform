"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, getCandles } from "@/lib/api";
import { mergeOlderCandles } from "@/lib/chartHistoryMerge";
import type { Candle, CandlesResponse, Timeframe } from "@/lib/types";

import type { AsyncResource } from "./useAsyncResource";

// How many older bars a single pan-left page request pulls -- generous
// enough that a user panning continuously rarely has to wait on back-to-back
// requests, bounded enough to keep intraday in-memory growth sane.
const OLDER_PAGE_LIMIT = 500;

export interface CandleHistoryPagination {
  /** Base candles plus every older page loaded so far, ascending, deduped. */
  candles: Candle[];
  loadingOlder: boolean;
  historyExhausted: boolean;
  error: string | null;
  /** Wired to CandlestickChart's `onNeedOlderHistory` -- a no-op while a
   * request is already in flight, history is exhausted, or the previous
   * request is sitting in an unretried error state (never an automatic
   * retry loop; the user must invoke `retry()` explicitly). */
  loadOlder: () => void;
  /** Explicit retry after a failed older-history request -- the chart and
   * its already-loaded candles are untouched by the prior failure. */
  retry: () => void;
}

/**
 * FINAL TERMINAL POLISH PASS (#1): lazy pan-left historical loading state,
 * layered on top of the existing `useCandles` base fetch (symbol/timeframe/
 * range) rather than replacing it. `base` is trusted as the single source of
 * truth for "a fresh load happened" -- its `data` object gets a brand new
 * identity exactly when symbol, timeframe, or range (via the limit passed
 * into useCandles) changes, which is also exactly when accumulated older
 * pages must be thrown away (SPY panned back to 2018, then switching to
 * NVDA must not carry SPY's pagination history).
 */
export function useCandleHistoryPagination(
  symbol: string,
  timeframe: Timeframe,
  base: AsyncResource<CandlesResponse>,
): CandleHistoryPagination {
  const [olderCandles, setOlderCandles] = useState<Candle[]>([]);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [historyExhausted, setHistoryExhausted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cursorRef = useRef<string | null>(null);
  const inFlightRef = useRef(false);

  // Resets accumulated pagination state exactly when `base.data` gets a
  // brand new identity -- which only happens on a genuine fresh base fetch
  // (symbol, timeframe, or range change), never on an unrelated re-render.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOlderCandles([]);
    setLoadingOlder(false);
    setError(null);
    setHistoryExhausted(base.data?.history_exhausted ?? false);
    cursorRef.current = base.data?.next_before ?? null;
    inFlightRef.current = false;
  }, [base.data]);

  const fetchOlder = useCallback(
    (cursor: string) => {
      inFlightRef.current = true;
      setLoadingOlder(true);
      setError(null);

      getCandles(symbol, timeframe, OLDER_PAGE_LIMIT, cursor)
        .then((response) => {
          inFlightRef.current = false;
          setLoadingOlder(false);
          setOlderCandles((prev) => mergeOlderCandles(prev, response.candles));
          if (response.history_exhausted) {
            setHistoryExhausted(true);
          }
          cursorRef.current =
            response.next_before ?? (response.candles.length > 0 ? response.candles[0].timestamp : null);
          if (!cursorRef.current) {
            // Nothing older came back and no cursor to continue with --
            // honestly exhausted, never guessed.
            setHistoryExhausted(true);
          }
        })
        .catch((err: unknown) => {
          inFlightRef.current = false;
          setLoadingOlder(false);
          // Preserve currently displayed candles and the cursor -- a failed
          // page is never treated as history exhaustion, and `retry()` can
          // re-attempt the exact same cursor.
          setError(err instanceof ApiError ? err.message : "Failed to load older history");
        });
    },
    [symbol, timeframe],
  );

  const loadOlder = useCallback(() => {
    if (inFlightRef.current || historyExhausted || error) return;
    const cursor = cursorRef.current;
    if (!cursor) return;
    fetchOlder(cursor);
  }, [historyExhausted, error, fetchOlder]);

  const retry = useCallback(() => {
    if (inFlightRef.current) return;
    const cursor = cursorRef.current;
    if (!cursor) return;
    fetchOlder(cursor);
  }, [fetchOlder]);

  const baseCandles = base.data?.candles ?? [];
  return {
    candles: olderCandles.length > 0 ? mergeOlderCandles(baseCandles, olderCandles) : baseCandles,
    loadingOlder,
    historyExhausted,
    error,
    loadOlder,
    retry,
  };
}
