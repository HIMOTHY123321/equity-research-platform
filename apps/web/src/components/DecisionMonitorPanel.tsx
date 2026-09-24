"use client";

import { DecisionPlanCard } from "@/components/DecisionPlanCard";
import { GlossaryHint } from "@/components/GlossaryHint";
import type { AsyncResource } from "@/hooks/useAsyncResource";
import type { DecisionPlan } from "@/lib/types";

const TERMINAL_STATES = new Set(["abstain", "invalidated", "exit_conditions_met", "expired"]);

/**
 * The Decision Monitor -- one card per DecisionPlan for the current symbol/
 * timeframe. Open plans (still being actively monitored) are shown first,
 * terminal plans (abstained/invalidated/exited/expired) below, so multiple
 * simultaneous or contradictory setups (§32 of the Phase 13 spec) are all
 * visible at once rather than collapsed into one summary. Presentational
 * only -- fetching lives in useDecisionPlans(), owned by MarketWorkspace.
 */
export function DecisionMonitorPanel({ symbol, query }: { symbol: string | null; query: AsyncResource<DecisionPlan[]> }) {
  const { data: plans, state, error } = query;

  if (!symbol) {
    return <div className="p-4 text-xs text-muted">Select a symbol to monitor.</div>;
  }
  if (state === "loading") {
    return <div className="p-4 text-xs text-muted">Scanning for setups…</div>;
  }
  if (state === "error") {
    return <div className="p-4 text-xs text-negative">{error}</div>;
  }
  if (!plans || plans.length === 0) {
    return (
      <div className="flex h-16 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
        No decision plans for {symbol} right now.
      </div>
    );
  }

  const open = plans.filter((p) => !TERMINAL_STATES.has(p.state));
  const terminal = plans.filter((p) => TERMINAL_STATES.has(p.state));

  return (
    <div className="space-y-4">
      <h3 className="flex items-center gap-1 text-[11px] font-semibold tracking-wide text-muted">
        DECISION MONITOR — {symbol}
        <GlossaryHint termId="decision-plan" />
      </h3>
      <p className="text-[10px] text-muted">
        Research-state monitoring only -- never a BUY/SELL recommendation. See RANKING GATE for research-strength context.
      </p>

      {open.length > 0 ? (
        <ul className="space-y-2">
          {open.map((plan) => (
            <DecisionPlanCard key={plan.decision_plan_id} plan={plan} />
          ))}
        </ul>
      ) : (
        <div className="flex h-12 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
          No actively monitored plans right now.
        </div>
      )}

      {terminal.length > 0 && (
        <div>
          <h4 className="mb-2 text-[10px] font-semibold tracking-wide text-muted">RESOLVED / ABSTAINED</h4>
          <ul className="space-y-2">
            {terminal.map((plan) => (
              <DecisionPlanCard key={plan.decision_plan_id} plan={plan} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
