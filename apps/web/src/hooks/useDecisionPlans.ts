"use client";

import { getDecisionEvidence, getDecisionExplanations, getDecisionTransitions, scanDecisions } from "@/lib/api";
import type { DecisionEvidencePacket, DecisionExplanations, DecisionPlan, DecisionTransition, Timeframe } from "@/lib/types";

import { useAsyncResource, type AsyncResource } from "./useAsyncResource";

/**
 * Scans (creates any new DecisionPlans for newly-qualified setups, then
 * re-evaluates every already-open plan) and returns the full current list
 * for one symbol/timeframe -- the Decision Monitor's single data source.
 * `symbol === null` never fetches (no ticker selected yet).
 */
export function useDecisionPlans(
  symbol: string | null,
  timeframe: Timeframe,
  refreshKey?: number,
): AsyncResource<DecisionPlan[]> {
  return useAsyncResource(
    () => (symbol ? scanDecisions(symbol, timeframe) : Promise.resolve([])),
    [symbol, timeframe, refreshKey],
  );
}

export function useDecisionTransitions(decisionPlanId: string | null): AsyncResource<DecisionTransition[]> {
  return useAsyncResource(
    () => (decisionPlanId ? getDecisionTransitions(decisionPlanId) : Promise.resolve([])),
    [decisionPlanId],
  );
}

export function useDecisionEvidence(decisionPlanId: string | null): AsyncResource<DecisionEvidencePacket> {
  return useAsyncResource(
    () => (decisionPlanId ? getDecisionEvidence(decisionPlanId) : Promise.resolve(null as unknown as DecisionEvidencePacket)),
    [decisionPlanId],
  );
}

export function useDecisionExplanations(decisionPlanId: string | null): AsyncResource<DecisionExplanations> {
  return useAsyncResource(
    () => (decisionPlanId ? getDecisionExplanations(decisionPlanId) : Promise.resolve(null as unknown as DecisionExplanations)),
    [decisionPlanId],
  );
}
