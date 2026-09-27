"use client";

import { useEffect, useState } from "react";

import { TopNav } from "@/components/TopNav";
import {
  ApiError,
  getDevSimulatorStatus,
  pushDevSimulatorDisconnect,
  pushDevSimulatorTrade,
  type DevSimulatorStatus,
} from "@/lib/api";

/**
 * Phase 17 (§60/§79/§99): lets a developer hand-script
 * app.live.mock_streaming.MockStreamingProvider (a trade push, a simulated
 * disconnect) to preview live-chart UX -- forming candles, reconnect/
 * RESYNCING, eventually gap-fill -- without any real provider account.
 * Every push here flows through the real backend LiveMarketService
 * pipeline; open a chart for the same symbol in another tab to watch it
 * arrive. If /api/dev/live-simulator 404s (not enabled on the backend),
 * this renders an honest "not enabled" message rather than a broken form.
 */
export function LiveSimulatorClient() {
  const [status, setStatus] = useState<DevSimulatorStatus | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [symbol, setSymbol] = useState("SPY");
  const [price, setPrice] = useState("100.00");
  const [lastAction, setLastAction] = useState<string | null>(null);

  function refreshStatus() {
    getDevSimulatorStatus()
      .then((s) => {
        setStatus(s);
        setUnavailable(false);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setUnavailable(true);
        }
      });
  }

  useEffect(() => {
    refreshStatus();
    const interval = setInterval(refreshStatus, 2000);
    return () => clearInterval(interval);
  }, []);

  async function handlePushTrade() {
    const parsedPrice = Number(price);
    if (!symbol || Number.isNaN(parsedPrice)) return;
    await pushDevSimulatorTrade(symbol.toUpperCase(), parsedPrice);
    setLastAction(`Pushed trade ${symbol.toUpperCase()} @ ${parsedPrice}`);
    refreshStatus();
  }

  async function handleDisconnect() {
    await pushDevSimulatorDisconnect();
    setLastAction("Pushed simulated disconnect");
    refreshStatus();
  }

  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-6 py-6">
        <div>
          <h1 className="font-mono text-lg font-semibold">Dev Live Simulator</h1>
          <p className="mt-1 text-xs text-muted">
            Development-only. Pushes synthetic trades/disconnects into the real live-data pipeline so
            you can preview forming candles, reconnect, and gap-fill UX without a real provider account.
          </p>
        </div>

        {unavailable ? (
          <section className="rounded-md border border-border bg-surface p-4 text-xs text-muted">
            The dev live simulator is not enabled on this backend. Set{" "}
            <code className="rounded bg-background px-1">ENABLE_DEV_LIVE_SIMULATOR=true</code> in a
            non-production environment to use this page.
          </section>
        ) : (
          <>
            <section className="rounded-md border border-border bg-surface p-4">
              <h2 className="mb-3 font-mono text-xs font-semibold uppercase tracking-wide text-muted">
                Push a trade
              </h2>
              <div className="flex flex-wrap items-end gap-3">
                <label className="flex flex-col gap-1 text-xs">
                  Symbol
                  <input
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                    className="rounded-md border border-border bg-background px-2 py-1 text-xs"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs">
                  Price
                  <input
                    value={price}
                    onChange={(e) => setPrice(e.target.value)}
                    className="rounded-md border border-border bg-background px-2 py-1 text-xs"
                  />
                </label>
                <button
                  type="button"
                  onClick={handlePushTrade}
                  className="rounded-md border border-border px-3 py-1.5 text-xs hover:border-positive hover:text-positive"
                >
                  Push trade
                </button>
              </div>
            </section>

            <section className="rounded-md border border-border bg-surface p-4">
              <h2 className="mb-3 font-mono text-xs font-semibold uppercase tracking-wide text-muted">
                Connection
              </h2>
              <button
                type="button"
                onClick={handleDisconnect}
                className="rounded-md border border-border px-3 py-1.5 text-xs hover:border-negative hover:text-negative"
              >
                Simulate disconnect
              </button>
            </section>

            {lastAction && <p className="text-xs text-muted">{lastAction}</p>}

            <section className="rounded-md border border-border bg-surface p-4">
              <h2 className="mb-3 font-mono text-xs font-semibold uppercase tracking-wide text-muted">
                Status
              </h2>
              {status ? (
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                  <dt className="text-muted">Connected</dt>
                  <dd>{String(status.connected)}</dd>
                  <dt className="text-muted">Connect count</dt>
                  <dd>{status.connect_count}</dd>
                  <dt className="text-muted">Subscriptions</dt>
                  <dd>{Object.keys(status.subscriptions).join(", ") || "none"}</dd>
                </dl>
              ) : (
                <p className="text-xs text-muted">Loading…</p>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
