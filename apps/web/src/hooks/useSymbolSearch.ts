"use client";

import { useEffect, useRef, useState } from "react";

import { searchSymbols } from "@/lib/api";
import type { SymbolMatch } from "@/lib/types";

const DEBOUNCE_MS = 200;

/** (MARKET UX COMPLETION PASS #3/#9) Debounced ticker/company-name search
 * with a small in-memory cache keyed by (query, watchlist) so repeatedly
 * typing back over an already-searched prefix doesn't refetch, and a stale
 * in-flight request never overwrites a newer one's results. Every state
 * update happens inside the debounce timer's callback (never synchronously
 * in the effect body) so a change of `query` can't trigger a cascading
 * render before the timer's own async boundary. */
export function useSymbolSearch(query: string, watchlistTickers: string[] = []) {
  const [results, setResults] = useState<SymbolMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cacheRef = useRef<Map<string, SymbolMatch[]>>(new Map());
  const latestRequestId = useRef(0);

  useEffect(() => {
    const requestId = ++latestRequestId.current;
    const trimmed = query.trim();
    const cacheKey = `${trimmed.toUpperCase()}|${watchlistTickers.join(",")}`;
    const cached = cacheRef.current.get(cacheKey);

    const timer = setTimeout(
      () => {
        if (requestId !== latestRequestId.current) return;
        if (!trimmed) {
          setResults([]);
          setLoading(false);
          setError(null);
          return;
        }
        if (cached) {
          setResults(cached);
          setLoading(false);
          setError(null);
          return;
        }
        setLoading(true);
        setError(null);
        searchSymbols(trimmed, watchlistTickers)
          .then((res) => {
            if (requestId !== latestRequestId.current) return; // superseded by a newer request
            cacheRef.current.set(cacheKey, res.results);
            setResults(res.results);
            setLoading(false);
          })
          .catch(() => {
            if (requestId !== latestRequestId.current) return;
            setError("Search failed");
            setLoading(false);
          });
      },
      trimmed && !cached ? DEBOUNCE_MS : 0,
    );

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- watchlistTickers compared by content, not identity
  }, [query, watchlistTickers.join(",")]);

  return { results, loading, error };
}
