"use client";

import { useCallback, useEffect, useState } from "react";

import { useLiveGlobalEvent } from "@/hooks/useLiveSymbol";
import { acknowledgeAlert, acknowledgeAllAlerts, getUnreadAlertCount, listAlerts } from "@/lib/api";
import type { AlertEvent } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

/**
 * The Alert Center's single data source (§16): an initial fetch plus live
 * updates via the shared WebSocket's `alert_event` frames (§19) -- a new
 * alert is prepended, never causing a second fetch of the whole list.
 *
 * `unreadIds` is tracked separately from `alerts` (fetched via its own
 * unread_only=true query) because AlertEvent itself carries no read/unread
 * field -- read state lives in a separate AlertAcknowledgementRecord on the
 * backend (§17), so acknowledging never mutates the immutable alert data
 * this hook also holds.
 */
export function useAlerts(params: { symbol?: string; severity?: string } = {}): {
  alerts: AlertEvent[];
  state: LoadState;
  error: string | null;
  unreadIds: Set<string>;
  unreadCount: number;
  acknowledge: (alertId: string) => Promise<void>;
  acknowledgeAll: () => Promise<void>;
} {
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [unreadIds, setUnreadIds] = useState<Set<string>>(new Set());
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const { symbol, severity } = params;

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState("loading");
    Promise.all([listAlerts({ symbol, severity }), listAlerts({ symbol, unreadOnly: true, limit: 1000 })])
      .then(([list, unread]) => {
        if (cancelled) return;
        setAlerts(list);
        setUnreadIds(new Set(unread.map((a) => a.alert_id)));
        setState("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setError("Failed to load alerts");
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, severity]);

  useLiveGlobalEvent(
    useCallback(
      (frame) => {
        if (frame.type !== "alert_event") return;
        if (symbol && frame.alert.symbol !== symbol) return;
        if (severity && frame.alert.severity !== severity) return;
        setAlerts((prev) => [frame.alert, ...prev.filter((a) => a.alert_id !== frame.alert.alert_id)]);
        setUnreadIds((prev) => new Set(prev).add(frame.alert.alert_id));
      },
      [symbol, severity],
    ),
  );

  const acknowledge = useCallback(async (alertId: string) => {
    await acknowledgeAlert(alertId);
    setUnreadIds((prev) => {
      const next = new Set(prev);
      next.delete(alertId);
      return next;
    });
  }, []);

  const acknowledgeAllHandler = useCallback(async () => {
    await acknowledgeAllAlerts(symbol);
    setUnreadIds(new Set());
  }, [symbol]);

  return {
    alerts,
    state,
    error,
    unreadIds,
    unreadCount: unreadIds.size,
    acknowledge,
    acknowledgeAll: acknowledgeAllHandler,
  };
}

/** Lightweight unread-count-only subscription for the nav badge -- avoids
 * every mounted component that just wants the count also fetching/holding
 * the full alert list. */
export function useUnreadAlertCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getUnreadAlertCount().then((res) => {
      if (!cancelled) setCount(res.count);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useLiveGlobalEvent(
    useCallback((frame) => {
      if (frame.type === "alert_event") setCount((prev) => prev + 1);
    }, []),
  );

  return count;
}
