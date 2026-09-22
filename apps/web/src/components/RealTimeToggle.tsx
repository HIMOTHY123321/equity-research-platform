"use client";

/**
 * MARKET EXPERIENCE COMPLETION PASS (#2/#10): REAL TIME is a separate
 * live-follow STATE, not an interval -- combinable with any candle
 * interval ("REAL TIME + 1m", "REAL TIME + 5m"). Strictly gated on genuine
 * streaming capability (`streamingActive`, sourced from
 * `/api/live/status`'s `streaming_active`, never a hardcoded provider-name
 * check) -- a provider being "connected" is not enough. With yfinance
 * (polling only) this control is always visible but disabled, and never
 * silently activates.
 */
export function RealTimeToggle({
  active,
  streamingActive,
  onToggle,
}: {
  active: boolean;
  streamingActive: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={!streamingActive}
      title={
        streamingActive
          ? "Toggle live-follow mode: chart, price, bid/ask, and forming candle update automatically."
          : "REAL TIME requires a genuine streaming provider entitlement. The current provider (yfinance) only polls -- showing LATEST AVAILABLE instead."
      }
      className={`flex items-center gap-1 rounded border px-2 py-1 font-mono text-[10px] uppercase tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        active && streamingActive
          ? "border-positive bg-positive/15 text-positive"
          : "border-border text-muted hover:text-foreground"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${active && streamingActive ? "bg-positive" : "bg-muted"}`}
      />
      Real Time
    </button>
  );
}
