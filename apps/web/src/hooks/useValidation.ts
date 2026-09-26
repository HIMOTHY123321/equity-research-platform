"use client";

import {
  getHistoricalComparison,
  getProspectiveObservations,
  getSignalGate,
  getSignalGateHistory,
  getValidationCohort,
  getValidationStatus,
  getValidationSummary,
} from "@/lib/api";
import type {
  CohortStatistics,
  HistoricalProspectiveComparison,
  ObservationStatus,
  ProspectiveObservation,
  SignalGateEvaluation,
  SignalGateHistoryEntry,
  Timeframe,
  ValidationSummary,
} from "@/lib/types";

import { useAsyncResource, type AsyncResource } from "./useAsyncResource";

export function useValidationStatus(): AsyncResource<ObservationStatus> {
  return useAsyncResource(() => getValidationStatus(), []);
}

export function useSignalGate(timeframe: Timeframe = "1h"): AsyncResource<SignalGateEvaluation> {
  return useAsyncResource(() => getSignalGate(timeframe), [timeframe]);
}

export function useSignalGateHistory(limit = 50): AsyncResource<SignalGateHistoryEntry[]> {
  return useAsyncResource(() => getSignalGateHistory(limit), [limit]);
}

export function useProspectiveObservations(params: {
  symbol?: string;
  setupType?: string;
  direction?: string;
  timeframe?: string;
  eventType?: string;
  resolvedOnly?: boolean;
} = {}): AsyncResource<ProspectiveObservation[]> {
  return useAsyncResource(
    () => getProspectiveObservations(params),
    [params.symbol, params.setupType, params.direction, params.timeframe, params.eventType, params.resolvedOnly],
  );
}

export function useValidationCohort(params: {
  eventType: string;
  horizonBars?: number;
  timeframe?: Timeframe;
  symbol?: string;
  setupType?: string;
  direction?: string;
}): AsyncResource<CohortStatistics> {
  return useAsyncResource(
    () => getValidationCohort(params),
    [params.eventType, params.horizonBars, params.timeframe, params.symbol, params.setupType, params.direction],
  );
}

export function useHistoricalComparison(
  params: { symbol: string; setupType: string; direction: string; horizonBars?: number } | null,
): AsyncResource<HistoricalProspectiveComparison> {
  return useAsyncResource(
    () =>
      params
        ? getHistoricalComparison(params)
        : Promise.resolve({
            cohort_label: "",
            historical_n: 0,
            historical_median_effect: null,
            prospective_n: 0,
            prospective_median_effect: null,
            direction_agreement: null,
            magnitude_agreement: null,
            note: "No cohort selected.",
          }),
    [params?.symbol, params?.setupType, params?.direction, params?.horizonBars],
  );
}

export function useValidationSummary(
  params: { timeframe?: Timeframe; horizonBars?: number } = {},
): AsyncResource<ValidationSummary> {
  return useAsyncResource(() => getValidationSummary(params), [params.timeframe, params.horizonBars]);
}
