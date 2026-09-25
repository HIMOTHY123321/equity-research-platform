"use client";

import Link from "next/link";

import { formatDecisionState, formatExchangeTimestamp } from "@/lib/format";
import type { AlertEvent } from "@/lib/types";

const SEVERITY_STYLES: Record<string, string> = {
  info: "bg-muted/15 text-muted",
  notice: "bg-accent/15 text-accent",
  important: "bg-warning/15 text-warning",
  critical: "bg-negative/15 text-negative",
};

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        SEVERITY_STYLES[severity] ?? "bg-muted/15 text-muted"
      }`}
    >
      {severity}
    </span>
  );
}

export function AlertCard({
  alert,
  read,
  onAcknowledge,
}: {
  alert: AlertEvent;
  read: boolean;
  onAcknowledge: (alertId: string) => void;
}) {
  const deepLink = alert.decision_plan_id
    ? `/?symbol=${alert.symbol}&decision=${alert.decision_plan_id}`
    : `/?symbol=${alert.symbol}`;

  return (
    <li
      className={`rounded border p-3 ${
        read ? "border-border bg-surface" : "border-accent/40 bg-surface-raised"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <SeverityBadge severity={alert.severity} />
          <span className="text-xs font-semibold text-foreground">{alert.symbol}</span>
          {alert.current_state && (
            <span className="text-[10px] uppercase text-muted">{formatDecisionState(alert.current_state)}</span>
          )}
        </div>
        {!read && (
          <button
            type="button"
            onClick={() => onAcknowledge(alert.alert_id)}
            className="text-[10px] uppercase text-muted hover:text-foreground"
          >
            Mark as read
          </button>
        )}
      </div>

      <p className="mt-1.5 text-xs text-foreground">{alert.title}</p>
      <p className="mt-0.5 text-[11px] text-muted">{alert.summary}</p>

      <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-muted">
        <span>{formatExchangeTimestamp(alert.occurred_at)}</span>
        <div className="flex items-center gap-2">
          {alert.origin !== "live_prospective" && (
            <span className="uppercase text-warning">{alert.origin.replace(/_/g, " ")}</span>
          )}
          {alert.decision_plan_id && (
            <Link href={deepLink} className="text-accent hover:underline">
              Open plan →
            </Link>
          )}
        </div>
      </div>
    </li>
  );
}
