"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";

export type LoadState = "loading" | "ready" | "error";

export interface AsyncResource<T> {
  data: T | null;
  state: LoadState;
  error: string | null;
}

/**
 * One fetch per dependency change, shared by every useXyz market-data hook
 * so MarketWorkspace can request each resource exactly once and hand the
 * result down to both a panel and a chart overlay -- no duplicate fetches
 * for the same data. `fetcher` is intentionally excluded from the effect's
 * dependency array: callers pass a fresh inline closure each render, but
 * its actual inputs (symbol, timeframe, ...) are already what's listed in
 * `deps`, so re-running only when those change (not on every render) is
 * correct, not stale -- the effect still captures whichever closure was
 * current on the render that triggered it.
 */
export function useAsyncResource<T>(fetcher: () => Promise<T>, deps: readonly unknown[]): AsyncResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Standard React data-fetching-effect pattern -- see MarketWorkspace.tsx
    // (the original home of this pattern) for the fuller justification.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState("loading");
    setError(null);

    fetcher()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setState("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load data");
        setState("error");
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, state, error };
}
