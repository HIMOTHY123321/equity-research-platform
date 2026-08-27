"use client";

import { getCandles, getFeatures, getLevels, getSetups, getStructure } from "@/lib/api";
import type {
  CandlesResponse,
  FeatureSnapshot,
  MarketStructureSnapshot,
  SetupDetectionSnapshot,
  SupportResistanceSnapshot,
  Timeframe,
} from "@/lib/types";

import { useAsyncResource, type AsyncResource } from "./useAsyncResource";

export function useCandles(symbol: string, timeframe: Timeframe, limit = 300): AsyncResource<CandlesResponse> {
  return useAsyncResource(() => getCandles(symbol, timeframe, limit), [symbol, timeframe, limit]);
}

export function useFeatures(symbol: string, timeframe: Timeframe): AsyncResource<FeatureSnapshot> {
  return useAsyncResource(() => getFeatures(symbol, timeframe), [symbol, timeframe]);
}

export function useStructure(symbol: string, timeframe: Timeframe): AsyncResource<MarketStructureSnapshot> {
  return useAsyncResource(() => getStructure(symbol, timeframe), [symbol, timeframe]);
}

export function useLevels(symbol: string, timeframe: Timeframe): AsyncResource<SupportResistanceSnapshot> {
  return useAsyncResource(() => getLevels(symbol, timeframe), [symbol, timeframe]);
}

export function useSetups(symbol: string, timeframe: Timeframe): AsyncResource<SetupDetectionSnapshot> {
  return useAsyncResource(() => getSetups(symbol, timeframe), [symbol, timeframe]);
}
