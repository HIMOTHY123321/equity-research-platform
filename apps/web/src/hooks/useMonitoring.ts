"use client";

import { useCallback, useEffect, useState } from "react";

import { disableMonitoring, enableMonitoring, listMonitoring } from "@/lib/api";

/**
 * The monitoring-universe toggle state (§8/§22) -- deliberately separate
 * from Watchlist membership itself; a symbol can be on the Watchlist
 * without being monitored, or monitored without being on the Watchlist.
 * Failures are swallowed (never surfaced as a hard error) since this is a
 * secondary affordance layered onto the Watchlist row, not its primary
 * purpose -- an unreachable /api/monitoring just leaves toggles showing
 * their last-known state.
 */
export function useMonitoringSubscriptions(): {
  isMonitored: (symbol: string) => boolean;
  toggle: (symbol: string) => void;
} {
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    listMonitoring()
      .then((subs) => {
        if (cancelled) return;
        setEnabled(Object.fromEntries(subs.map((s) => [s.symbol, s.enabled])));
      })
      .catch(() => {
        // No monitoring data yet -- toggles default to "off" until a real
        // read succeeds; never blocks or breaks the rest of the Watchlist.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = useCallback((symbol: string) => {
    setEnabled((prev) => {
      const next = !prev[symbol];
      (next ? enableMonitoring(symbol) : disableMonitoring(symbol)).catch(() => {
        // Revert on failure -- optimistic update only, never lies about
        // persisted state on a genuine backend error.
        setEnabled((current) => ({ ...current, [symbol]: !next }));
      });
      return { ...prev, [symbol]: next };
    });
  }, []);

  return { isMonitored: (symbol) => enabled[symbol] ?? false, toggle };
}
