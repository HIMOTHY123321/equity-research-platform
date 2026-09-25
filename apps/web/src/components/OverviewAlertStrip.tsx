"use client";

import Link from "next/link";

import { useAlerts } from "@/hooks/useAlerts";
import { formatDecisionState, formatExchangeTimestamp } from "@/lib/format";

/**
 * §40: a compact summary on Overview -- latest important/critical alert,
 * unread count, link to the Alert Center and Decision Scanner. Deliberately
 * NOT a replacement for the Decision Monitor (a deep view of one symbol/
 * setup) or the Alert Center (full history) -- just enough to notice
 * something happened without staring at an individual ticker.
 */
export function OverviewAlertStrip() {
  const { alerts, unreadCount } = useAlerts();
  const latestNotable = alerts.find((a) => a.severity === "important" || a.severity === "critical") ?? null;

  if (!latestNotable && unreadCount === 0) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 py-2 text-xs">
      <div className="flex items-center gap-2">
        {latestNotable ? (
          <>
            <span
              className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                latestNotable.severity === "critical" ? "bg-negative/15 text-negative" : "bg-warning/15 text-warning"
              }`}
            >
              {latestNotable.severity}
            </span>
            <span className="font-semibold text-foreground">{latestNotable.symbol}</span>
            {latestNotable.current_state && (
              <span className="text-muted">{formatDecisionState(latestNotable.current_state)}</span>
            )}
            <span className="text-muted">{latestNotable.title}</span>
            <span className="text-[10px] text-muted">{formatExchangeTimestamp(latestNotable.occurred_at)}</span>
          </>
        ) : (
          <span className="text-muted">{unreadCount} unread alert{unreadCount === 1 ? "" : "s"}</span>
        )}
      </div>
      <div className="flex items-center gap-3 text-[11px]">
        <Link href="/scanner" className="text-accent hover:underline">
          Scanner →
        </Link>
        <Link href="/alerts" className="text-accent hover:underline">
          Alert Center{unreadCount > 0 ? ` (${unreadCount})` : ""} →
        </Link>
      </div>
    </div>
  );
}
