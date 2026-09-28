"use client";

import Link from "next/link";

import { useAsyncResource } from "@/hooks/useAsyncResource";
import { listAlerts } from "@/lib/api";
import { formatClockTime, formatDecisionState } from "@/lib/format";

/**
 * Phase 18 (§30): a compact "recent alerts for THIS symbol" panel inside
 * the Terminal, reusing the exact deep-link shape AlertCard/DecisionScanner
 * already build and test (`/?symbol=&decision=&timeframe=`) -- clicking an
 * entry re-navigates the SAME workspace with the target plan highlighted,
 * never a separate page. This is deliberately a thin list, not a second
 * Alert Center -- acknowledge/preferences stay on /alerts.
 */
export function RecentAlertsPanel({ symbol, limit = 5 }: { symbol: string; limit?: number }) {
  const { data, state, error } = useAsyncResource(
    () => listAlerts({ symbol, limit }),
    [symbol, limit],
  );

  if (state === "loading") return <p className="text-[11px] text-muted">Loading recent alerts…</p>;
  if (state === "error") return <p className="text-[11px] text-negative">{error}</p>;
  if (!data || data.length === 0) {
    return <p className="text-[11px] text-muted">No recent alerts for {symbol}.</p>;
  }

  return (
    <ul className="space-y-1">
      {data.map((alert) => {
        const deepLink = alert.decision_plan_id
          ? `/?symbol=${alert.symbol}&decision=${alert.decision_plan_id}${
              alert.timeframe ? `&timeframe=${alert.timeframe}` : ""
            }`
          : `/?symbol=${alert.symbol}`;
        return (
          <li key={alert.alert_id} className="flex items-center justify-between gap-2 text-[11px]">
            <span className="text-muted">{formatClockTime(alert.occurred_at)}</span>
            <span className="flex-1 truncate text-foreground">
              {alert.current_state ? formatDecisionState(alert.current_state) : alert.title}
            </span>
            {alert.decision_plan_id ? (
              <Link href={deepLink} className="text-accent hover:underline">
                Open →
              </Link>
            ) : (
              <span className="text-muted">—</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
