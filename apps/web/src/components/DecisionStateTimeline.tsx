"use client";

import { useDecisionTransitions } from "@/hooks/useDecisionPlans";
import { formatDecisionState, formatExchangeTimestamp } from "@/lib/format";

/**
 * Full lifecycle timeline for one DecisionPlan (§ "state timeline" of the
 * Phase 13 spec) -- every transition ever recorded, oldest first, each with
 * its full timestamp-to-second + EST/EDT and the deterministic reason the
 * engine recorded at the moment it happened. Nothing here is re-derived;
 * it is a direct read of the append-only transition ledger.
 */
export function DecisionStateTimeline({ decisionPlanId }: { decisionPlanId: string }) {
  const { data: transitions, state, error } = useDecisionTransitions(decisionPlanId);

  if (state === "loading") {
    return <p className="text-[11px] text-muted">Loading timeline…</p>;
  }
  if (state === "error") {
    return <p className="text-[11px] text-negative">{error}</p>;
  }
  if (!transitions || transitions.length === 0) {
    return <p className="text-[11px] text-muted">No transitions recorded yet.</p>;
  }

  return (
    <ol className="space-y-2 border-l border-border pl-3">
      {transitions.map((t) => (
        <li key={t.transition_id} className="text-[11px]">
          <div className="flex items-center gap-1.5">
            {t.from_state && <span className="text-muted">{formatDecisionState(t.from_state)}</span>}
            {t.from_state && <span className="text-muted">→</span>}
            <span className="font-semibold text-foreground">{formatDecisionState(t.to_state)}</span>
          </div>
          <div className="font-mono text-[10px] text-muted">{formatExchangeTimestamp(t.occurred_at)}</div>
          <p className="text-muted">{t.reason}</p>
        </li>
      ))}
    </ol>
  );
}
