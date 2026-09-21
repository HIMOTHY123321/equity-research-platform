import { MarketWorkspace } from "@/components/MarketWorkspace";
import { TopNav } from "@/components/TopNav";
import { checkApiHealth } from "@/lib/api";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ symbol?: string }>;
}) {
  const health = await checkApiHealth();
  // Lets a Watchlist row link (`/?symbol=NVDA`) select that ticker on
  // arrival, instead of always resetting to the hardcoded default (§18).
  const { symbol } = await searchParams;
  const defaultSymbol = symbol?.trim() ? symbol.trim().toUpperCase() : "SPY";

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

        <MarketWorkspace defaultSymbol={defaultSymbol} />
      </main>
    </div>
  );
}
