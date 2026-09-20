"use client";

import { getForecastGate, getForecastPerformance, listForecasts } from "@/lib/api";
import type { ForecastPerformanceResponse, ForwardForecast, ForwardValidationGateEvaluation } from "@/lib/types";

import { useAsyncResource, type AsyncResource } from "./useAsyncResource";

export function useForecastList(
  params: { symbol?: string; timeframe?: string; status?: string; refreshKey?: number } = {},
): AsyncResource<ForwardForecast[]> {
  return useAsyncResource(
    () => listForecasts({ symbol: params.symbol, timeframe: params.timeframe, status: params.status }),
    [params.symbol, params.timeframe, params.status, params.refreshKey],
  );
}

export function useForecastPerformance(symbol?: string, refreshKey?: number): AsyncResource<ForecastPerformanceResponse> {
  return useAsyncResource(() => getForecastPerformance(symbol), [symbol, refreshKey]);
}

export function useForecastGate(refreshKey?: number): AsyncResource<ForwardValidationGateEvaluation> {
  return useAsyncResource(() => getForecastGate(), [refreshKey]);
}
