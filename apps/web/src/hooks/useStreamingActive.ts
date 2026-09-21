"use client";

import { useEffect, useState } from "react";

import { getLiveStatus } from "@/lib/api";
import { useLiveConnectionState } from "@/hooks/useLiveSymbol";

/**
 * Hardening pass (§5): whether the *active* market data provider is
 * genuinely push-streaming (Massive with a real entitlement) vs. polled
 * (yfinance fallback) -- fetched once from /api/live/status (the backend's
 * one source of truth for provider capabilities) and refetched whenever
 * the WebSocket connection state changes, since a reconnect can follow a
 * provider/config change. Defaults to `false` (never assume streaming) for
 * the brief window before the first response arrives.
 */
export function useStreamingActive(): boolean {
  const [streamingActive, setStreamingActive] = useState(false);
  const connectionState = useLiveConnectionState();

  useEffect(() => {
    let cancelled = false;
    getLiveStatus()
      .then((status) => {
        if (!cancelled) setStreamingActive(status.streaming_active);
      })
      .catch(() => {
        if (!cancelled) setStreamingActive(false);
      });
    return () => {
      cancelled = true;
    };
  }, [connectionState]);

  return streamingActive;
}
