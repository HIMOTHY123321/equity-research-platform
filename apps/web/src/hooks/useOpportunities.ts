"use client";

import { useAsyncResource, type AsyncResource } from "@/hooks/useAsyncResource";
import { getOpportunities } from "@/lib/api";
import type { OpportunityListResponse, Timeframe } from "@/lib/types";

/**
 * Phase 19 (Part 2): Opportunity Intelligence's data source -- a plain
 * read-model fetch, re-run whenever the filter/sort/timeframe params
 * change. Unlike the Decision Scanner this deliberately does NOT
 * auto-refresh on every live WebSocket event (Part 11: composing this
 * across the whole universe is comparatively cheap per request, but still
 * not something to re-run on every tick) -- the caller re-fetches by
 * changing one of the params below.
 */
export function useOpportunities(params: {
  timeframe?: Timeframe;
  category?: string;
  setupType?: string;
  sort?: "state" | "symbol" | "recency";
}): AsyncResource<OpportunityListResponse> {
  return useAsyncResource(
    () => getOpportunities(params),
    [params.timeframe, params.category, params.setupType, params.sort],
  );
}
