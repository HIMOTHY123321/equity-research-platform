"use client";

import {
  getDecisionEvidence,
  getDecisionEvidenceDiffs,
  getDecisionExplanations,
  getDecisionTransitions,
  scanDecisions,
} from "@/lib/api";
import type {
  DecisionEvidencePacket,
  DecisionExplanations,
  DecisionPlan,
  DecisionTransition,
  EvidenceDiffSnapshot,
  Timeframe,
} from "@/lib/types";

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

/** Phase 18 (§11): oldest-first list of every recorded EvidenceDiffSnapshot
 * for this plan -- the caller renders the most recent ("WHAT CHANGED SINCE
 * LAST STATE") and may show earlier ones as history. Empty (never an
 * error) for a plan that has never had an activation snapshot to diff
 * against yet (e.g. still WATCHING/ABSTAIN). */
export function useDecisionEvidenceDiffs(decisionPlanId: string | null): AsyncResource<EvidenceDiffSnapshot[]> {
  return useAsyncResource(
    () => (decisionPlanId ? getDecisionEvidenceDiffs(decisionPlanId) : Promise.resolve([])),
    [decisionPlanId],
  );
}
