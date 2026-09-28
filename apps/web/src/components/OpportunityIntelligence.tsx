"use client";

import Link from "next/link";
import { useState } from "react";

import { useOpportunities } from "@/hooks/useOpportunities";
import { formatEnumLabel, formatExchangeTimestamp } from "@/lib/format";
import type { AttentionCategoryKind, OpportunityCandidate, Timeframe } from "@/lib/types";

const CATEGORY_STYLES: Record<AttentionCategoryKind, string> = {
  entry_conditions_met: "bg-positive/15 text-positive",
  active_thesis: "bg-positive/15 text-positive",
  thesis_strengthening: "bg-positive/15 text-positive",
  near_setup: "bg-accent/15 text-accent",
  watching: "bg-accent/15 text-accent",
  mixed: "bg-warning/15 text-warning",
  abstain: "bg-muted/15 text-muted",
  insufficient_data: "bg-muted/15 text-muted",
};

// Factual filters only (Part 2: "never labeled predictive ranking") --
// every option here is a Decision-state-derived category or a plain
// recency/alphabetical sort, never an implied "best" ordering.
const CATEGORY_FILTERS: { id: string; label: string; category?: AttentionCategoryKind }[] = [
  { id: "all", label: "All" },
  { id: "entry_conditions_met", label: "Entry Conditions Met", category: "entry_conditions_met" },
  { id: "active_thesis", label: "Active Thesis", category: "active_thesis" },
  { id: "thesis_strengthening", label: "Strengthening", category: "thesis_strengthening" },
  { id: "near_setup", label: "Near Setup", category: "near_setup" },
  { id: "watching", label: "Watching", category: "watching" },
  { id: "mixed", label: "Mixed", category: "mixed" },
  { id: "abstain", label: "Abstain", category: "abstain" },
  { id: "insufficient_data", label: "Insufficient Data", category: "insufficient_data" },
];

function CategoryBadge({ category }: { category: AttentionCategoryKind }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${CATEGORY_STYLES[category] ?? "bg-muted/15 text-muted"}`}
    >
      {formatEnumLabel(category)}
    </span>
  );
}

export function OpportunityIntelligence({ defaultTimeframe = "1h" as Timeframe }: { defaultTimeframe?: Timeframe }) {
  const [timeframe, setTimeframe] = useState<Timeframe>(defaultTimeframe);
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState<"state" | "symbol" | "recency">("state");

  const activeFilter = CATEGORY_FILTERS.find((f) => f.id === filter)!;
  const { data, state, error } = useOpportunities({ timeframe, category: activeFilter.category, sort });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {CATEGORY_FILTERS.map((f) => (
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
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value as Timeframe)}
            className="rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground"
          >
            {(["15m", "1h", "4h", "1d"] as Timeframe[]).map((tf) => (
              <option key={tf} value={tf}>
                {tf.toUpperCase()}
              </option>
            ))}
          </select>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as "state" | "symbol" | "recency")}
            className="rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground"
          >
            <option value="state">Sort: Decision-state order</option>
            <option value="symbol">Sort: Symbol</option>
            <option value="recency">Sort: Most recent</option>
          </select>
        </div>
      </div>

      {data && (
        <p className="text-[10px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
          {data.ranking_validation_message}
        </p>
      )}

      {state === "loading" && <p className="text-xs text-muted">Loading opportunities…</p>}
      {state === "error" && <p className="text-xs text-negative">{error}</p>}
      {state === "ready" && data && data.candidates.length === 0 && (
        <p className="text-xs text-muted">No symbols in the monitoring universe match this filter.</p>
      )}

      {state === "ready" && data && data.candidates.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted">
                <th className="px-3 py-2">Symbol</th>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2">Why</th>
                <th className="px-3 py-2">As Of</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {data.candidates.map((candidate) => (
                <OpportunityRow key={candidate.symbol} candidate={candidate} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OpportunityRow({ candidate }: { candidate: OpportunityCandidate }) {
  // Same &timeframe= requirement DecisionScanner's deep link already
  // established -- without it, Overview's default timeframe rarely matches
  // and the highlight silently never lands.
  const href = candidate.decision_plan_id
    ? `/?symbol=${candidate.symbol}&decision=${candidate.decision_plan_id}&timeframe=${candidate.timeframe}`
    : `/?symbol=${candidate.symbol}&timeframe=${candidate.timeframe}`;
  return (
    <tr className="border-b border-border/60 last:border-0 hover:bg-surface-raised/50">
      <td className="px-3 py-2 font-semibold text-foreground">{candidate.symbol}</td>
      <td className="px-3 py-2">
        <CategoryBadge category={candidate.category} />
      </td>
      <td className="max-w-md px-3 py-2 text-muted">{candidate.why}</td>
      <td className="px-3 py-2 text-muted">{formatExchangeTimestamp(candidate.as_of)}</td>
      <td className="px-3 py-2 text-right">
        <Link href={href} className="text-accent hover:underline">
          Open →
        </Link>
      </td>
    </tr>
  );
}
