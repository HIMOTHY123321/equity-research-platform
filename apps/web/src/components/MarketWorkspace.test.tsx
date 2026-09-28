import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// This test exercises the real wiring between the sidebar Watchlist and
// MarketWorkspace's URL-driven symbol state (the actual regression under
// test: "click NVDA -> URL becomes /?symbol=NVDA"). Every other panel is
// heavy (lightweight-charts, its own network calls) and irrelevant to that
// wiring, so they're stubbed out; only Watchlist and the router/API layer
// underneath it are real.
const pushMock = vi.fn();
let currentSearch = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => new URLSearchParams(currentSearch),
}));

vi.mock("@/hooks/useLiveSymbol", () => ({
  useLiveSymbol: () => ({ quote: null, candles: {}, connectionState: "connected" }),
  useLiveConnectionState: () => "connected",
  // Phase 14: useAlerts/useDecisionScanner (pulled in transitively via the
  // sidebar Watchlist's Decision-state dot/monitoring toggle) subscribe to
  // this -- a no-op unsubscribe is all this wiring test needs.
  useLiveGlobalEvent: () => {},
}));

vi.mock("@/hooks/useStreamingActive", () => ({
  useStreamingActive: () => false,
}));

vi.mock("@/components/CandlestickChart", () => ({
  CandlestickChart: () => <div data-testid="chart-stub" />,
  DEFAULT_CHART_DISPLAY_OPTIONS: { structure: true, supportResistance: true, setups: true, allPivots: false, decisions: true },
}));
vi.mock("@/components/ChartLegend", () => ({ ChartLegend: () => null }));
vi.mock("@/components/FeaturePanel", () => ({ FeaturePanel: () => null }));
vi.mock("@/components/SetupInspectorPanel", () => ({ SetupInspectorPanel: () => null }));
vi.mock("@/components/DecisionMonitorPanel", () => ({ DecisionMonitorPanel: () => null }));
vi.mock("@/components/StructurePanel", () => ({ StructurePanel: () => null }));
vi.mock("@/components/SupportResistancePanel", () => ({ SupportResistancePanel: () => null }));
vi.mock("@/components/LiveQuoteHeader", () => ({ LiveQuoteHeader: () => null }));
vi.mock("@/components/StockThesisPanel", () => ({ StockThesisPanel: () => null }));
vi.mock("@/components/SymbolCatalystTimeline", () => ({ SymbolCatalystTimeline: () => null }));
vi.mock("@/components/WhatsMovingPanel", () => ({ WhatsMovingPanel: () => null }));
vi.mock("@/components/RecentAlertsPanel", () => ({ RecentAlertsPanel: () => null }));
vi.mock("@/components/ValidationStatusWidget", () => ({ ValidationStatusWidget: () => null }));

import { MarketWorkspace } from "./MarketWorkspace";
import * as api from "@/lib/api";
import type { WatchlistSymbol } from "@/lib/types";

const SYMBOLS: WatchlistSymbol[] = [
  { ticker: "AAPL", added_at: "2026-01-01T00:00:00Z" },
  { ticker: "NVDA", added_at: "2026-01-02T00:00:00Z" },
  { ticker: "SPY", added_at: "2026-01-03T00:00:00Z" },
];

describe("MarketWorkspace <-> sidebar Watchlist wiring (regression)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    pushMock.mockClear();
    currentSearch = "symbol=SPY";
    vi.spyOn(api, "getWatchlist").mockResolvedValue(SYMBOLS);
    vi.spyOn(api, "getCandles").mockResolvedValue({
      symbol: "SPY",
      timeframe: "1d",
      candles: [],
      has_more: false,
      history_exhausted: true,
      next_before: null,
    });
    vi.spyOn(api, "getFeatures").mockRejectedValue(new Error("not needed for this test"));
    vi.spyOn(api, "getStructure").mockRejectedValue(new Error("not needed for this test"));
    vi.spyOn(api, "getLevels").mockRejectedValue(new Error("not needed for this test"));
    vi.spyOn(api, "getSetups").mockRejectedValue(new Error("not needed for this test"));
    vi.spyOn(api, "getSymbolCatalysts").mockRejectedValue(new Error("not needed for this test"));
    vi.spyOn(api, "scanDecisions").mockRejectedValue(new Error("not needed for this test"));
    vi.spyOn(api, "getDecisionScanner").mockResolvedValue([]);
    vi.spyOn(api, "listMonitoring").mockResolvedValue([]);
  });

  it("clicking NVDA in the sidebar watchlist calls router.push with ?symbol=NVDA", async () => {
    render(<MarketWorkspace defaultSymbol="SPY" />);
    await waitFor(() => expect(screen.getByText("NVDA")).toBeInTheDocument());

    fireEvent.click(screen.getByText("NVDA").closest("button")!);

    expect(pushMock).toHaveBeenCalledTimes(1);
    const [url, options] = pushMock.mock.calls[0];
    expect(url).toBe("?symbol=NVDA");
    // push, never replace -- each symbol change must be a real back-stack
    // entry so browser back/forward can restore the prior ticker.
    expect(options).toEqual({ scroll: false });
  });

  it("the chart heading reflects the currently-selected symbol from the URL", async () => {
    currentSearch = "symbol=NVDA";
    render(<MarketWorkspace defaultSymbol="SPY" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "NVDA" })).toBeInTheDocument());
  });

  // Phase 13.1 regression: the workspace's real content used to be gated
  // entirely behind a Suspense boundary around useSearchParams() (see the
  // architecture comment above SymbolUrlWatcher in MarketWorkspace.tsx) --
  // a cold load in a real browser never called MarketWorkspaceInner's
  // render function at all until a user interaction forced a flush, with
  // no console error or failed request to reveal why. useSearchParams() is
  // now isolated to a tiny leaf (SymbolUrlWatcher) so the heavy tree
  // (MarketWorkspaceInner) is never itself wrapped in that Suspense
  // boundary and paints synchronously using `defaultSymbol`. This asserts
  // that synchronous first paint directly, without `waitFor` -- if
  // MarketWorkspaceInner ever again depended on an async/Suspense-gated
  // value to render its heading at all, this would fail immediately.
  it("paints real content synchronously on mount using defaultSymbol, before any URL sync", () => {
    currentSearch = ""; // no ?symbol= present -- forces reliance on defaultSymbol alone
    render(<MarketWorkspace defaultSymbol="AAPL" />);
    expect(screen.getByRole("heading", { name: "AAPL" })).toBeInTheDocument();
  });

  // Phase 14.1 regression: an Alert/Scanner deep link
  // (`/?symbol=X&decision=Y&timeframe=Z`) must open directly on the linked
  // DecisionPlan's own timeframe. Before this fix, `timeframe` was pure
  // local state hardcoded to "1d", so a 1h-plan deep link silently fetched
  // 1d plans instead -- the linked plan was never even in the response,
  // and the highlight in DecisionMonitorPanel had nothing to match against.
  it("a ?timeframe= deep link drives the initial decision-plan fetch, not the 1d default", async () => {
    currentSearch = "symbol=QQQ&decision=plan-1&timeframe=1h";
    const scanSpy = vi.spyOn(api, "scanDecisions").mockResolvedValue([]);

    render(<MarketWorkspace defaultSymbol="SPY" />);

    await waitFor(() => expect(scanSpy).toHaveBeenCalledWith("QQQ", "1h"));
  });

  it("an invalid ?timeframe= value falls back to the 1d default rather than crashing", async () => {
    currentSearch = "symbol=QQQ&timeframe=not-a-real-timeframe";
    const scanSpy = vi.spyOn(api, "scanDecisions").mockResolvedValue([]);

    render(<MarketWorkspace defaultSymbol="SPY" />);

    await waitFor(() => expect(scanSpy).toHaveBeenCalledWith("QQQ", "1d"));
  });

  it("selecting a timeframe calls router.push with ?timeframe=", async () => {
    currentSearch = "symbol=SPY";
    render(<MarketWorkspace defaultSymbol="SPY" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "SPY" })).toBeInTheDocument());

    pushMock.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "1H" }));

    expect(pushMock).toHaveBeenCalledTimes(1);
    const [url, options] = pushMock.mock.calls[0];
    expect(url).toBe("?timeframe=1h");
    // push, never replace -- same back-stack contract as symbol changes,
    // so browser back/forward restores the prior timeframe too.
    expect(options).toEqual({ scroll: false });
  });

  // Phase 18 (Priority 11, §44): every ancillary panel's query
  // (features/structure/levels/setups/catalysts/decisions) already
  // rejects in this file's own beforeEach -- this test makes that an
  // explicit, named error-isolation guarantee: the chart/header still
  // render normally regardless. Each panel below is mocked separately in
  // its own test file (loading/error branches); this proves the workspace
  // as a whole doesn't crash or blank out when several panels fail at once.
  it("Phase 18 (Priority 11): chart and header remain usable when every ancillary panel query fails", async () => {
    currentSearch = "symbol=SPY";
    render(<MarketWorkspace defaultSymbol="SPY" />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "SPY" })).toBeInTheDocument());
    // Candles themselves resolve successfully in this suite's beforeEach
    // (empty array) -- the chart area shows the honest "no candles" state
    // rather than crashing, which is what actually proves every OTHER
    // panel's rejection didn't take the whole tree down with it.
    expect(screen.getByText(/no candles returned for spy/i)).toBeInTheDocument();
  });
});
