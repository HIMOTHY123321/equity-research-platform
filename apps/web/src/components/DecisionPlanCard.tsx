"use client";

import { useState } from "react";

import { DecisionStateTimeline } from "@/components/DecisionStateTimeline";
import { GlossaryHint } from "@/components/GlossaryHint";
import { useDecisionExplanations } from "@/hooks/useDecisionPlans";
import { formatDecisionState, formatDetectionTime, formatSetupType } from "@/lib/format";
import type { DecisionCondition, DecisionPlan } from "@/lib/types";

const STATE_STYLES: Record<string, string> = {
  detected: "bg-muted/15 text-muted",
  evaluating: "bg-muted/15 text-muted",
  abstain: "bg-muted/15 text-muted",
  watching: "bg-accent/15 text-accent",
  entry_conditions_met: "bg-positive/15 text-positive",
  active_thesis: "bg-positive/15 text-positive",
  thesis_strengthening: "bg-positive/15 text-positive",
  thesis_weakening: "bg-warning/15 text-warning",
  invalidated: "bg-negative/15 text-negative",
  exit_conditions_met: "bg-muted/15 text-muted",
  expired: "bg-muted/15 text-muted",
};

const STATE_GLOSSARY_ID: Record<string, string> = {
  watching: "watching",
  entry_conditions_met: "entry-conditions-met",
  active_thesis: "active-thesis",
  thesis_strengthening: "thesis-strengthening",
  thesis_weakening: "thesis-weakening",
  invalidated: "invalidated",
  exit_conditions_met: "exit-conditions-met",
  expired: "expired",
};

function StateBadge({ state }: { state: string }) {
  const glossaryId = STATE_GLOSSARY_ID[state];
  return (
    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${STATE_STYLES[state] ?? "bg-muted/15 text-muted"}`}>
      {formatDecisionState(state)}
      {glossaryId && <GlossaryHint termId={glossaryId} />}
    </span>
  );
}

function ConditionRow({ condition }: { condition: DecisionCondition }) {
  const symbol = condition.status === "passed" ? "✓" : condition.status === "failed" ? "✕" : condition.status === "unavailable" ? "?" : "…";
  const color =
    condition.status === "passed" ? "text-positive" : condition.status === "failed" ? "text-negative" : "text-muted";
  return (
    <div className="flex items-start justify-between gap-2 text-[11px]">
      <span className={color}>
        {symbol} {condition.description}
      </span>
      {(condition.actual_value !== null || condition.required_value !== null) && (
        <span className="whitespace-nowrap font-mono text-muted">
          {condition.actual_value === null ? "—" : condition.actual_value.toFixed(2)} /{" "}
          {condition.required_value === null ? "—" : condition.required_value.toFixed(2)}
        </span>
      )}
    </div>
  );
}

function ExplanationBlock({ decisionPlanId }: { decisionPlanId: string }) {
  const { data, state, error } = useDecisionExplanations(decisionPlanId);
  if (state === "loading") return <p className="text-[11px] text-muted">Loading explanation…</p>;
  if (state === "error") return <p className="text-[11px] text-negative">{error}</p>;
  if (!data) return null;
  return (
    <div className="space-y-2 rounded border border-border bg-background p-2">
      <div>
        <h5 className="text-[10px] font-semibold tracking-wide text-muted">WHY NOT YET</h5>
        <p className="whitespace-pre-line text-[11px] text-foreground">{data.why_not_yet}</p>
      </div>
      <div>
        <h5 className="text-[10px] font-semibold tracking-wide text-muted">WHY NOW</h5>
        <p className="whitespace-pre-line text-[11px] text-foreground">{data.why_now}</p>
      </div>
      {data.what_would_change_state.length > 0 && (
        <div>
          <h5 className="text-[10px] font-semibold tracking-wide text-muted">WHAT WOULD CHANGE THE STATE</h5>
          <ul className="list-inside list-disc text-[11px] text-foreground">
            {data.what_would_change_state.map((line, idx) => (
              <li key={idx}>{line}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function DecisionPlanCard({
  plan,
  highlighted = false,
}: {
  plan: DecisionPlan;
  /** Phase 14 §25 deep linking: true when this card was opened via an
   * `/alerts` or Decision Scanner "Open plan" link -- auto-expands and
   * visually marks it so the user lands directly on the relevant plan
   * instead of having to find it among possibly several open plans. */
  highlighted?: boolean;
}) {
  const [expanded, setExpanded] = useState(highlighted);
  const lastTransition = plan.transitions[plan.transitions.length - 1] ?? null;
  const missingEntry = plan.entry_conditions.filter((c) => c.status !== "passed");

  return (
    <li
      className={`rounded border p-3 ${
        highlighted ? "border-accent bg-surface-raised ring-1 ring-accent/50" : "border-border bg-surface-raised"
      }`}
    >
      <div className="flex w-full items-start justify-between gap-2">
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="flex flex-1 items-start justify-between gap-2 text-left"
        >
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-foreground">{formatSetupType(plan.setup_type)}</span>
              <span className={`text-[10px] uppercase ${plan.direction === "bullish" ? "text-positive" : "text-negative"}`}>
                {plan.direction}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-muted">
              Detected {formatDetectionTime(plan.created_at, plan.timeframe)}
              {lastTransition ? ` · last change: ${lastTransition.reason}` : ""}
            </p>
          </div>
          <span className="text-[11px] text-muted">{expanded ? "▲" : "▼"}</span>
        </button>
        {/* Outside the toggle <button> deliberately: StateBadge's GlossaryHint
            renders its own <button>, and a <button> can never nest inside
            another <button> without triggering a hydration error. */}
        <StateBadge state={plan.state} />
      </div>

      {plan.research_status.length > 0 && (
        <p className="mt-1 text-[10px] uppercase tracking-wide text-warning">{plan.research_status.join(" · ").replace(/_/g, " ")}</p>
      )}

      {expanded && (
        <div className="mt-2 space-y-3 border-t border-border pt-2">
          {plan.state === "watching" && missingEntry.length > 0 && (
            <div className="space-y-1">
              <h5 className="text-[10px] font-semibold tracking-wide text-muted">MISSING ENTRY CONDITIONS</h5>
              {missingEntry.map((c) => (
                <ConditionRow key={c.id} condition={c} />
              ))}
            </div>
          )}
          {plan.entry_conditions.some((c) => c.status === "passed") && (
            <div className="space-y-1">
              <h5 className="text-[10px] font-semibold tracking-wide text-muted">SATISFIED ENTRY CONDITIONS</h5>
              {plan.entry_conditions
                .filter((c) => c.status === "passed")
                .map((c) => (
                  <ConditionRow key={c.id} condition={c} />
                ))}
            </div>
          )}
          {plan.invalidation_conditions.length > 0 && (
            <div className="space-y-1">
              <h5 className="text-[10px] font-semibold tracking-wide text-muted">INVALIDATION</h5>
              {plan.invalidation_conditions.map((c) => (
                <ConditionRow key={c.id} condition={c} />
              ))}
            </div>
          )}
          {plan.exit_conditions.length > 0 && (
            <div className="space-y-1">
              <h5 className="text-[10px] font-semibold tracking-wide text-muted">EXIT CONDITIONS</h5>
              {plan.exit_conditions.map((c) => (
                <ConditionRow key={c.id} condition={c} />
              ))}
            </div>
          )}

          <ExplanationBlock decisionPlanId={plan.decision_plan_id} />

          <div>
            <h5 className="mb-1 text-[10px] font-semibold tracking-wide text-muted">STATE TIMELINE</h5>
            <DecisionStateTimeline decisionPlanId={plan.decision_plan_id} />
          </div>
        </div>
      )}
    </li>
  );
}
