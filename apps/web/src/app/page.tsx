import { MarketWorkspace } from "@/components/MarketWorkspace";
import { OverviewAlertStrip } from "@/components/OverviewAlertStrip";
import { TopNav } from "@/components/TopNav";
import { checkApiHealth } from "@/lib/api";
import { TIMEFRAMES, type Timeframe } from "@/lib/types";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ symbol?: string; timeframe?: string }>;
}) {
  const health = await checkApiHealth();
  // Lets a Watchlist row link (`/?symbol=NVDA`) select that ticker on
  // arrival, instead of always resetting to the hardcoded default (§18).
  const { symbol, timeframe } = await searchParams;
  const defaultSymbol = symbol?.trim() ? symbol.trim().toUpperCase() : "SPY";
  // Phase 14.1: an Alert/Scanner deep link (`/?symbol=X&decision=Y&timeframe=Z`)
  // must open directly on the linked DecisionPlan's own timeframe -- without
  // this, the plan's timeframe almost never matches the hardcoded "1d"
  // default, DecisionMonitorPanel never even fetches it, and the highlight
  // silently never appears. Validated server-side (like defaultSymbol above)
  // so there's no first-paint flash of the wrong timeframe.
  const defaultTimeframe: Timeframe = (TIMEFRAMES as readonly string[]).includes(timeframe ?? "")
    ? (timeframe as Timeframe)
    : "1d";

  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-4 px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="font-mono text-lg font-semibold">Market Overview</h1>
          <div className="flex items-center gap-2 text-[11px] text-muted">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                health?.status === "ok" ? "bg-positive" : "bg-negative"
              }`}
            />
            API: {health?.status === "ok" ? `connected (${health.environment})` : "unreachable"}
          </div>
        </div>

        <OverviewAlertStrip />

        <MarketWorkspace defaultSymbol={defaultSymbol} defaultTimeframe={defaultTimeframe} />
      </main>
    </div>
  );
}
