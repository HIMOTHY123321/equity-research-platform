"use client";

import { useCallback, useEffect, useState } from "react";

import { useLiveGlobalEvent } from "@/hooks/useLiveSymbol";
import { getDecisionScanner } from "@/lib/api";
import type { ScannerRow } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

/**
 * The Decision Scanner's data source (§9/§36): an initial fetch, refreshed
 * whenever the live WebSocket reports a `decision_state_change` for any
 * monitored symbol -- the scanner itself never triggers a scan (that's the
 * background MonitoringService's job), it only re-reads already-persisted
 * state.
 */
export function useDecisionScanner(): { rows: ScannerRow[]; state: LoadState; error: string | null } {
  const [rows, setRows] = useState<ScannerRow[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState("loading");
    getDecisionScanner()
      .then((data) => {
        if (cancelled) return;
        setRows(data);
        setState("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setError("Failed to load the Decision Scanner");
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  useLiveGlobalEvent(
    useCallback((frame) => {
      if (frame.type === "decision_state_change") setReloadKey((n) => n + 1);
    }, []),
  );

  return { rows, state, error };
}
