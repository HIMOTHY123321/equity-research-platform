"use client";

import { useMemo, useState } from "react";

import { AlertCard } from "@/components/AlertCard";
import { useAlerts } from "@/hooks/useAlerts";

const FILTERS = [
  { id: "all", label: "All", severity: undefined },
  { id: "unread", label: "Unread", severity: undefined },
  { id: "important", label: "Important", severity: "important" },
  { id: "critical", label: "Critical", severity: "critical" },
] as const;

type FilterId = (typeof FILTERS)[number]["id"];

export function AlertCenter({ symbol }: { symbol?: string }) {
  const [filter, setFilter] = useState<FilterId>("all");
  const activeFilter = FILTERS.find((f) => f.id === filter)!;
  const { alerts, state, error, unreadIds, unreadCount, acknowledge, acknowledgeAll } = useAlerts({
    symbol,
    severity: activeFilter.severity,
  });

  const visible = useMemo(
    () => (filter === "unread" ? alerts.filter((a) => unreadIds.has(a.alert_id)) : alerts),
    [alerts, filter, unreadIds],
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              className={`rounded px-2 py-1 text-[11px] font-medium uppercase tracking-wide transition-colors ${
                filter === f.id ? "bg-surface-raised text-foreground" : "text-muted hover:text-foreground"
              }`}
            >
              {f.label}
              {f.id === "unread" && unreadCount > 0 && (
                <span className="ml-1 rounded-full bg-accent/20 px-1.5 text-accent">{unreadCount}</span>
              )}
            </button>
          ))}
        </div>
        {unreadCount > 0 && (
          <button
            type="button"
            onClick={() => acknowledgeAll()}
            className="text-[11px] text-muted hover:text-foreground"
          >
            Mark all as read
          </button>
        )}
      </div>

      {state === "loading" && <p className="text-xs text-muted">Loading alerts…</p>}
      {state === "error" && <p className="text-xs text-negative">{error}</p>}
      {state === "ready" && visible.length === 0 && (
        <p className="text-xs text-muted">No alerts{filter !== "all" ? ` (${activeFilter.label.toLowerCase()})` : ""}.</p>
      )}

      <ul className="flex flex-col gap-2">
        {visible.map((alert) => (
          <AlertCard
            key={alert.alert_id}
            alert={alert}
            read={!unreadIds.has(alert.alert_id)}
            onAcknowledge={acknowledge}
          />
        ))}
      </ul>
    </div>
  );
}
