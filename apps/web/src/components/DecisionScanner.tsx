"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { useDecisionScanner } from "@/hooks/useDecisionScanner";
import { formatDecisionState, formatExchangeTimestamp, formatSetupType } from "@/lib/format";
import type { DecisionStateKind, ScannerRow } from "@/lib/types";

const STATE_STYLES: Record<string, string> = {
  watching: "bg-accent/15 text-accent",
  entry_conditions_met: "bg-positive/15 text-positive",
  active_thesis: "bg-positive/15 text-positive",
  thesis_strengthening: "bg-positive/15 text-positive",
  thesis_weakening: "bg-warning/15 text-warning",
  invalidated: "bg-negative/15 text-negative",
  exit_conditions_met: "bg-negative/15 text-negative",
  expired: "bg-muted/15 text-muted",
  abstain: "bg-muted/15 text-muted",
};

// No "Best trade"/"Highest confidence"/"Top opportunity" sort options here
// by design (§38) -- only these, all either recency- or category-based.
type SortOption = "urgency" | "newest" | "symbol";

const FILTERS: { id: string; label: string; states?: DecisionStateKind[] }[] = [
  { id: "all", label: "All" },
  { id: "watching", label: "Watching", states: ["watching"] },
  { id: "entry", label: "Entry Conditions Met", states: ["entry_conditions_met"] },
  {
    id: "active",
    label: "Active",
    states: ["active_thesis", "thesis_strengthening", "thesis_weakening"],
  },
  { id: "weakening", label: "Weakening", states: ["thesis_weakening"] },
  { id: "invalidated", label: "Invalidated", states: ["invalidated"] },
  { id: "exit", label: "Exit Conditions Met", states: ["exit_conditions_met"] },
  { id: "abstain", label: "Abstain / No Plan", states: ["abstain"] },
];

function StateBadge({ state }: { state: DecisionStateKind | null }) {
  if (!state) {
    return <span className="inline-flex items-center rounded bg-muted/15 px-1.5 py-0.5 text-[10px] uppercase text-muted">No plan</span>;
  }
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${STATE_STYLES[state] ?? "bg-muted/15 text-muted"}`}>
      {formatDecisionState(state)}
    </span>
  );
}

export function DecisionScanner() {
  const { rows, state, error } = useDecisionScanner();
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState<SortOption>("urgency");
  const [symbolFilter, setSymbolFilter] = useState("");

  const activeFilter = FILTERS.find((f) => f.id === filter)!;

  const visible = useMemo(() => {
    let filtered = rows;
    if (activeFilter.states) {
      filtered = filtered.filter((r) => (r.state ? activeFilter.states!.includes(r.state) : filter === "abstain" && r.state === null));
    }
    if (symbolFilter.trim()) {
      const query = symbolFilter.trim().toUpperCase();
      filtered = filtered.filter((r) => r.symbol.includes(query));
    }
    if (sort === "symbol") {
      filtered = [...filtered].sort((a, b) => a.symbol.localeCompare(b.symbol));
    } else if (sort === "newest") {
      filtered = [...filtered].sort((a, b) => (b.last_change_at ?? "").localeCompare(a.last_change_at ?? ""));
    }
    // "urgency" is the backend's own default ordering -- left as-is.
    return filtered;
  }, [rows, activeFilter, symbolFilter, sort, filter]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              className={`rounded px-2 py-1 text-[10px] font-medium uppercase tracking-wide transition-colors ${
                filter === f.id ? "bg-surface-raised text-foreground" : "text-muted hover:text-foreground"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={symbolFilter}
            onChange={(e) => setSymbolFilter(e.target.value)}
            placeholder="Filter symbol…"
            className="w-28 rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground"
          />
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortOption)}
            className="rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground"
          >
            <option value="urgency">Sort: State urgency</option>
            <option value="newest">Sort: Newest change</option>
            <option value="symbol">Sort: Symbol</option>
          </select>
        </div>
      </div>

      {state === "loading" && <p className="text-xs text-muted">Loading scanner…</p>}
      {state === "error" && <p className="text-xs text-negative">{error}</p>}
      {state === "ready" && visible.length === 0 && <p className="text-xs text-muted">No monitored symbols match this filter.</p>}

      {state === "ready" && visible.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted">
                <th className="px-3 py-2">Symbol</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Setup</th>
                <th className="px-3 py-2">Timeframe</th>
                <th className="px-3 py-2">Direction</th>
                <th className="px-3 py-2">Last Change</th>
                <th className="px-3 py-2">Research Status</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <ScannerRowView key={row.symbol} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ScannerRowView({ row }: { row: ScannerRow }) {
  const href = row.decision_plan_id
    ? `/?symbol=${row.symbol}&decision=${row.decision_plan_id}`
    : `/?symbol=${row.symbol}`;
  return (
    <tr className="border-b border-border/60 last:border-0 hover:bg-surface-raised/50">
      <td className="px-3 py-2 font-semibold text-foreground">{row.symbol}</td>
      <td className="px-3 py-2">
        <StateBadge state={row.state} />
      </td>
      <td className="px-3 py-2 text-muted">{row.setup_type ? formatSetupType(row.setup_type) : "—"}</td>
      <td className="px-3 py-2 text-muted uppercase">{row.timeframe ?? "—"}</td>
      <td className={`px-3 py-2 uppercase ${row.direction === "bullish" ? "text-positive" : row.direction === "bearish" ? "text-negative" : "text-muted"}`}>
        {row.direction ?? "—"}
      </td>
      <td className="px-3 py-2 text-muted">{row.last_change_at ? formatExchangeTimestamp(row.last_change_at) : "—"}</td>
      <td className="px-3 py-2 text-[10px] uppercase text-warning">
        {row.research_status.length > 0 ? row.research_status.join(" · ").replace(/_/g, " ") : "—"}
        {row.other_monitored_plan_count > 0 && (
          <span className="ml-1 text-muted">+{row.other_monitored_plan_count} other monitored plans</span>
        )}
      </td>
      <td className="px-3 py-2 text-right">
        <Link href={href} className="text-accent hover:underline">
          Open →
        </Link>
      </td>
    </tr>
  );
}
