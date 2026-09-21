"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { liveClient } from "@/lib/liveClient";
import type {
  ConnectionStateKind,
  LiveCandle,
  LiveQuote,
  LiveServerFrame,
  LiveSubscriptionPriority,
} from "@/lib/types";

/**
 * The only supported way any component subscribes to live data (Phase
 * 12.1 #O). Mounting this hook for a symbol that's already subscribed
 * elsewhere in the tree does not open a second connection or a second
 * poll loop -- it just adds a ref and a listener to the shared
 * liveClient singleton; unmounting decrements the ref and unsubscribes
 * once nothing else needs that symbol.
 */
export function useLiveSymbol(
  symbol: string | null,
  timeframes: string[] = ["1h"],
  priority: LiveSubscriptionPriority = "viewed",
): { quote: LiveQuote | null; candles: Record<string, LiveCandle>; connectionState: ConnectionStateKind } {
  const [, forceRender] = useState(0);
  const connectionState = useLiveConnectionState();

  useEffect(() => {
    if (!symbol) return;
    liveClient.subscribe(symbol, timeframes, priority);
    const unlisten = liveClient.addSymbolListener(symbol, () => forceRender((n) => n + 1));
    return () => {
      unlisten();
      liveClient.unsubscribe(symbol);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, timeframes.join(","), priority]);

  if (!symbol) {
    return { quote: null, candles: {}, connectionState };
  }

  const quote = liveClient.getQuote(symbol);
  const candles: Record<string, LiveCandle> = {};
  for (const tf of timeframes) {
    const candle = liveClient.getCandle(symbol, tf);
    if (candle) candles[tf] = candle;
  }
  return { quote, candles, connectionState };
}

export function useLiveConnectionState(): ConnectionStateKind {
  return useSyncExternalStore(
    (onStoreChange) => liveClient.addConnectionListener(() => onStoreChange()),
    () => liveClient.getConnectionState(),
    () => "disconnected" as ConnectionStateKind,
  );
}

/** For consumers that care about a specific global event type (forecast
 * resolutions, catalyst updates) rather than a per-symbol quote/candle. */
export function useLiveGlobalEvent(onEvent: (frame: LiveServerFrame) => void): void {
  useEffect(() => liveClient.onGlobalEvent(onEvent), [onEvent]);
}
