import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useLiveSymbol", () => ({
  useLiveSymbol: vi.fn(),
}));
vi.mock("@/hooks/useStreamingActive", () => ({
  useStreamingActive: () => false,
}));

import { useLiveSymbol } from "@/hooks/useLiveSymbol";
import { LiveQuoteHeader } from "./LiveQuoteHeader";

const QUOTE = {
  symbol: "SPY",
  price: 500.12,
  bid: 500.1,
  ask: 500.14,
  spread: 0.04,
  is_approximate: true,
  previous_close: 498.0,
  percent_change: 0.43,
  freshness: {
    source_timestamp: "2026-06-15T13:30:00Z",
    received_at: "2026-06-15T13:30:01Z",
    age_seconds: 1,
    provider: "yfinance",
    market_session: "regular",
    freshness_state: "live",
  },
};

describe("Phase 18 (§4): LiveQuoteHeader market-header fields", () => {
  it("always shows bid/ask/spread/session even without a streaming provider", () => {
    vi.mocked(useLiveSymbol).mockReturnValue({
      quote: QUOTE as never,
      candles: {},
      connectionState: "connected",
    });

    render(<LiveQuoteHeader symbol="SPY" timeframe="1h" />);

    expect(screen.getByText(/Bid 500\.10 \/ Ask 500\.14/)).toBeInTheDocument();
    expect(screen.getByText(/Spread 0\.04/)).toBeInTheDocument();
    expect(screen.getByText(/Session: REGULAR/)).toBeInTheDocument();
  });

  it("shows Monitoring ON/OFF only when the caller passes a defined value", () => {
    vi.mocked(useLiveSymbol).mockReturnValue({
      quote: QUOTE as never,
      candles: {},
      connectionState: "connected",
    });

    const { rerender } = render(<LiveQuoteHeader symbol="SPY" timeframe="1h" />);
    expect(screen.queryByText(/Monitoring:/)).not.toBeInTheDocument();

    rerender(<LiveQuoteHeader symbol="SPY" timeframe="1h" monitored={true} />);
    expect(screen.getByText("Monitoring: ON")).toBeInTheDocument();

    rerender(<LiveQuoteHeader symbol="SPY" timeframe="1h" monitored={false} />);
    expect(screen.getByText("Monitoring: OFF")).toBeInTheDocument();
  });

  it("shows a waiting state with no quote yet, never a fabricated price", () => {
    vi.mocked(useLiveSymbol).mockReturnValue({
      quote: null,
      candles: {},
      connectionState: "connected",
    });

    render(<LiveQuoteHeader symbol="SPY" timeframe="1h" />);
    expect(screen.getByText("Waiting for live data…")).toBeInTheDocument();
  });
});
