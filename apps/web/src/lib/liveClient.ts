"use client";

import { getApiBaseUrl, getLiveStreamTicket } from "@/lib/api";
import type {
  ConnectionStateKind,
  LiveCandle,
  LiveQuote,
  LiveServerFrame,
  LiveSubscriptionPriority,
} from "@/lib/types";

/**
 * Phase 12.1 (#O/#P): the one centralized client-side subscription/cache
 * layer. A single module-level WebSocket connection is shared by every
 * component in the app -- `useLiveSymbol` (see hooks/useLiveSymbol.ts) is
 * the only supported way in; nothing outside this file ever opens its own
 * WebSocket or polls a symbol independently. Component A watching SPY and
 * Component B watching SPY share exactly one logical subscription, the
 * same way the backend's LiveMarketService shares one poll loop across
 * every WebSocket connection.
 */

type SymbolListener = () => void;
type ConnectionListener = (state: ConnectionStateKind) => void;

interface SymbolCacheEntry {
  quote: LiveQuote | null;
  candles: Map<string, LiveCandle>; // keyed by timeframe
  refCount: number;
  timeframes: Set<string>;
  priority: LiveSubscriptionPriority;
}

const RECONNECT_INITIAL_MS = 1000;
const RECONNECT_MAX_MS = 30000;

// Must match app.api.routes.live.WS_TICKET_SUBPROTOCOL on the backend
// exactly -- the fixed marker the server looks for as the FIRST offered
// Sec-WebSocket-Protocol entry, with the ticket itself as the second.
const WS_TICKET_SUBPROTOCOL = "ws-ticket";

// Mirrors app.live.config.SubscriptionPriority's ordering -- lower index
// wins when multiple hooks subscribe to the same symbol at different
// priorities (e.g. the viewed ticker is also on the watchlist).
const PRIORITY_RANK: LiveSubscriptionPriority[] = [
  "viewed",
  "active_forecast",
  "watchlist",
  "background_benchmark",
];

class LiveClient {
  private ws: WebSocket | null = null;
  private connectionState: ConnectionStateKind = "disconnected";
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly symbols = new Map<string, SymbolCacheEntry>();
  private readonly symbolListeners = new Map<string, Set<SymbolListener>>();
  private readonly connectionListeners = new Set<ConnectionListener>();
  private connecting = false;

  private wsUrl(): string {
    const base = getApiBaseUrl();
    return base.replace(/^http/, "ws") + "/api/live/stream";
  }

  private ensureConnected(): void {
    if (this.ws !== null || this.connecting) return;
    if (typeof window === "undefined") return; // never connect during SSR
    this.connecting = true;
    void this.connect();
  }

  private async connect(): Promise<void> {
    // Every (re)connect -- including every reconnect attempt scheduled by
    // scheduleReconnect below -- fetches a brand NEW ticket rather than
    // reusing one: tickets are single-use and live only ~45s, far shorter
    // than the reconnect backoff can grow to, so an old ticket would
    // already be rejected by the backend even before considering reuse.
    let ticket: string;
    try {
      ticket = (await getLiveStreamTicket()).ticket;
    } catch {
      this.connecting = false;
      this.scheduleReconnect();
      return;
    }
    // ensureConnected's guard above prevents a second concurrent connect
    // from starting, so this.ws is still null here.

    // Security review (post Phase 19.6): the ticket must NEVER appear in
    // the WebSocket URL -- a query string is far more likely to be
    // captured by a server access log, a reverse proxy's own logs, or
    // browser history than a Sec-WebSocket-Protocol value is (see
    // app.api.routes.live's WS_TICKET_SUBPROTOCOL docstring on the
    // backend for the full reasoning, which mirrors docs/deployment.md's
    // existing "nothing in this handshake's URL" rule and
    // app.market_data.twelve_data_provider's identical header-over-
    // query-string choice for its own API key). The WebSocket
    // constructor's second argument is the list of subprotocols offered
    // in the `Sec-WebSocket-Protocol` request header -- not part of the
    // URL/request-line at all.
    const socket = new WebSocket(this.wsUrl(), [WS_TICKET_SUBPROTOCOL, ticket]);
    this.ws = socket;

    socket.onopen = () => {
      this.connecting = false;
      this.reconnectAttempts = 0;
      // Resubscribe every symbol this client still cares about -- the
      // backend's own subscription state is per-connection, so a fresh
      // socket after a drop must re-announce interest (#Q "before
      // returning to LIVE, resynchronize").
      for (const [symbol, entry] of this.symbols) {
        if (entry.refCount > 0) this.sendSubscribe(symbol, [...entry.timeframes], entry.priority);
      }
    };

    socket.onmessage = (event) => {
      let frame: LiveServerFrame;
      try {
        frame = JSON.parse(event.data);
      } catch {
        return;
      }
      this.handleFrame(frame);
    };

    socket.onerror = () => {
      // onclose always fires after onerror for a WebSocket -- reconnect
      // logic lives there, not duplicated here.
    };

    socket.onclose = () => {
      this.connecting = false;
      this.ws = null;
      this.setConnectionState("disconnected");
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return;
    if (this.symbols.size === 0) return; // nothing to reconnect for
    const delay = Math.min(RECONNECT_INITIAL_MS * 2 ** this.reconnectAttempts, RECONNECT_MAX_MS);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.ensureConnected();
    }, delay);
  }

  private setConnectionState(state: ConnectionStateKind): void {
    if (state === this.connectionState) return;
    this.connectionState = state;
    for (const listener of this.connectionListeners) listener(state);
  }

  private handleFrame(frame: LiveServerFrame): void {
    switch (frame.type) {
      case "connection_status":
        this.setConnectionState(frame.status.state);
        return;
      case "heartbeat":
        return;
      case "quote": {
        const entry = this.entryFor(frame.symbol);
        entry.quote = frame.quote;
        this.notify(frame.symbol);
        return;
      }
      case "forming_candle":
      case "completed_candle": {
        const entry = this.entryFor(frame.symbol);
        entry.candles.set(frame.candle.timeframe, frame.candle);
        this.notify(frame.symbol);
        return;
      }
      case "snapshot_refreshed":
      case "forecast_resolved":
      case "catalyst_event":
      case "alert_event":
      case "decision_state_change":
      case "monitor_status":
        // Consumed by dedicated hooks (Forecast Lab / catalyst panels /
        // useAlerts / useDecisionScanner) via onGlobalEvent, not the
        // per-symbol quote/candle cache. Phase 14's three frame types are
        // broadcast to every connection regardless of symbol subscription
        // (see app.api.routes.live._UNIVERSE_WIDE_FRAME_TYPES) since the
        // Alert Center/Scanner show the whole monitored universe, not just
        // whatever symbol is currently viewed.
        this.notifyGlobal(frame);
        return;
      case "error":
        console.warn("live stream error:", frame.detail);
        return;
    }
  }

  private readonly globalListeners = new Set<(frame: LiveServerFrame) => void>();

  private notifyGlobal(frame: LiveServerFrame): void {
    for (const listener of this.globalListeners) listener(frame);
  }

  onGlobalEvent(listener: (frame: LiveServerFrame) => void): () => void {
    this.globalListeners.add(listener);
    return () => this.globalListeners.delete(listener);
  }

  private entryFor(symbol: string): SymbolCacheEntry {
    let entry = this.symbols.get(symbol);
    if (!entry) {
      entry = { quote: null, candles: new Map(), refCount: 0, timeframes: new Set(), priority: "viewed" };
      this.symbols.set(symbol, entry);
    }
    return entry;
  }

  private notify(symbol: string): void {
    const listeners = this.symbolListeners.get(symbol);
    if (!listeners) return;
    for (const listener of listeners) listener();
  }

  private sendSubscribe(symbol: string, timeframes: string[], priority: LiveSubscriptionPriority): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          action: "subscribe",
          symbol,
          timeframes: timeframes.length ? timeframes : ["1h"],
          priority,
        }),
      );
    }
  }

  private sendUnsubscribe(symbol: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "unsubscribe", symbol }));
    }
  }

  subscribe(symbol: string, timeframes: string[] = ["1h"], priority: LiveSubscriptionPriority = "viewed"): void {
    this.ensureConnected();
    const entry = this.entryFor(symbol);
    const isNew = entry.refCount === 0;
    entry.refCount += 1;
    const hadAllTimeframes = timeframes.every((tf) => entry.timeframes.has(tf));
    for (const tf of timeframes) entry.timeframes.add(tf);
    const priorityImproved = PRIORITY_RANK.indexOf(priority) < PRIORITY_RANK.indexOf(entry.priority);
    if (priorityImproved) entry.priority = priority;
    if (isNew || !hadAllTimeframes || priorityImproved) {
      this.sendSubscribe(symbol, [...entry.timeframes], entry.priority);
    }
  }

  unsubscribe(symbol: string): void {
    const entry = this.symbols.get(symbol);
    if (!entry) return;
    entry.refCount = Math.max(0, entry.refCount - 1);
    if (entry.refCount === 0) {
      this.sendUnsubscribe(symbol);
      this.symbols.delete(symbol);
      this.symbolListeners.delete(symbol);
    }
  }

  addSymbolListener(symbol: string, listener: SymbolListener): () => void {
    let listeners = this.symbolListeners.get(symbol);
    if (!listeners) {
      listeners = new Set();
      this.symbolListeners.set(symbol, listeners);
    }
    listeners.add(listener);
    return () => listeners?.delete(listener);
  }

  addConnectionListener(listener: ConnectionListener): () => void {
    this.connectionListeners.add(listener);
    listener(this.connectionState);
    return () => this.connectionListeners.delete(listener);
  }

  getQuote(symbol: string): LiveQuote | null {
    return this.symbols.get(symbol)?.quote ?? null;
  }

  getCandle(symbol: string, timeframe: string): LiveCandle | null {
    return this.symbols.get(symbol)?.candles.get(timeframe) ?? null;
  }

  getConnectionState(): ConnectionStateKind {
    return this.connectionState;
  }
}

// A true module-level singleton -- every import of this module across the
// whole app gets the same instance, which is what makes "one logical SPY
// subscription" possible without a React Context wrapper.
export const liveClient = new LiveClient();
