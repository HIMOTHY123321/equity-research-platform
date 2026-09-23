import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AsyncResource } from "./useAsyncResource";
import type { Candle, CandlesResponse } from "@/lib/types";

const { getCandlesMock } = vi.hoisted(() => ({ getCandlesMock: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, getCandles: getCandlesMock };
});

import { ApiError } from "@/lib/api";

import { useCandleHistoryPagination } from "./useCandleHistoryPagination";

function candle(timestamp: string): Candle {
  return {
    symbol: "SPY",
    timeframe: "1d",
    timestamp,
    session: "regular",
    open: 100,
    high: 101,
    low: 99,
    close: 100.5,
    volume: 1000,
  };
}

function baseResource(overrides: Partial<CandlesResponse> = {}): AsyncResource<CandlesResponse> {
  return {
    state: "ready",
    error: null,
    data: {
      symbol: "SPY",
      timeframe: "1d",
      candles: [candle("2026-01-05T00:00:00Z"), candle("2026-01-06T00:00:00Z")],
      has_more: true,
      history_exhausted: false,
      next_before: "2026-01-05T00:00:00Z",
      ...overrides,
    },
  };
}

beforeEach(() => {
  getCandlesMock.mockReset();
});

describe("useCandleHistoryPagination", () => {
  it("starts with just the base candles, not loading, not exhausted", () => {
    const base = baseResource();
    const { result } = renderHook(() => useCandleHistoryPagination("SPY", "1d", base));
    expect(result.current.candles).toHaveLength(2);
    expect(result.current.loadingOlder).toBe(false);
    expect(result.current.historyExhausted).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("sets loadingOlder while a request is in flight and merges the older page on success", async () => {
    let resolveFetch: (value: CandlesResponse) => void = () => {};
    getCandlesMock.mockReturnValue(
      new Promise<CandlesResponse>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const base = baseResource();
    const { result } = renderHook(() => useCandleHistoryPagination("SPY", "1d", base));

    act(() => result.current.loadOlder());
    expect(result.current.loadingOlder).toBe(true);

    await act(async () => {
      resolveFetch({
        symbol: "SPY",
        timeframe: "1d",
        candles: [candle("2026-01-03T00:00:00Z"), candle("2026-01-04T00:00:00Z")],
        has_more: true,
        history_exhausted: false,
        next_before: "2026-01-03T00:00:00Z",
      });
    });

    expect(result.current.loadingOlder).toBe(false);
    expect(result.current.candles.map((c) => c.timestamp)).toEqual([
      "2026-01-03T00:00:00Z",
      "2026-01-04T00:00:00Z",
      "2026-01-05T00:00:00Z",
      "2026-01-06T00:00:00Z",
    ]);
  });

  it("request lock: a second loadOlder() call while one is in flight does not issue a second fetch", () => {
    getCandlesMock.mockReturnValue(new Promise(() => {})); // never resolves
    const base = baseResource();
    const { result } = renderHook(() => useCandleHistoryPagination("SPY", "1d", base));

    act(() => {
      result.current.loadOlder();
      result.current.loadOlder();
      result.current.loadOlder();
    });

    expect(getCandlesMock).toHaveBeenCalledTimes(1);
  });

  it("does not fetch when the base response already reports history exhausted", () => {
    const base = baseResource({ has_more: false, history_exhausted: true, next_before: null });
    const { result } = renderHook(() => useCandleHistoryPagination("SPY", "1d", base));

    act(() => result.current.loadOlder());
    expect(getCandlesMock).not.toHaveBeenCalled();
    expect(result.current.historyExhausted).toBe(true);
  });

  it("marks history exhausted once a page comes back short/exhausted, and further loadOlder calls are no-ops", async () => {
    getCandlesMock.mockResolvedValue({
      symbol: "SPY",
      timeframe: "1d",
      candles: [candle("2026-01-04T00:00:00Z")],
      has_more: false,
      history_exhausted: true,
      next_before: null,
    } satisfies CandlesResponse);

    const base = baseResource();
    const { result } = renderHook(() => useCandleHistoryPagination("SPY", "1d", base));

    await act(async () => result.current.loadOlder());
    expect(result.current.historyExhausted).toBe(true);

    await act(async () => result.current.loadOlder());
    expect(getCandlesMock).toHaveBeenCalledTimes(1);
  });

  it("on fetch failure: preserves existing candles, sets a non-exhausting error, and does not retry automatically", async () => {
    getCandlesMock.mockRejectedValue(new ApiError(502, "upstream down"));
    const base = baseResource();
    const { result } = renderHook(() => useCandleHistoryPagination("SPY", "1d", base));

    await act(async () => result.current.loadOlder());

    expect(result.current.error).toBe("upstream down");
    expect(result.current.historyExhausted).toBe(false);
    expect(result.current.candles).toHaveLength(2); // untouched

    // A subsequent auto-triggered loadOlder() (e.g. the chart still near
    // the edge) must not silently retry -- only explicit retry() may.
    await act(async () => result.current.loadOlder());
    expect(getCandlesMock).toHaveBeenCalledTimes(1);
  });

  it("retry() re-attempts the same cursor after a failure and clears the error on success", async () => {
    getCandlesMock.mockRejectedValueOnce(new ApiError(502, "upstream down"));
    getCandlesMock.mockResolvedValueOnce({
      symbol: "SPY",
      timeframe: "1d",
      candles: [candle("2026-01-04T00:00:00Z")],
      has_more: true,
      history_exhausted: false,
      next_before: "2026-01-04T00:00:00Z",
    } satisfies CandlesResponse);

    const base = baseResource();
    const { result } = renderHook(() => useCandleHistoryPagination("SPY", "1d", base));

    await act(async () => result.current.loadOlder());
    expect(result.current.error).toBe("upstream down");

    await act(async () => result.current.retry());
    expect(result.current.error).toBeNull();
    expect(result.current.candles.map((c) => c.timestamp)).toContain("2026-01-04T00:00:00Z");
    expect(getCandlesMock).toHaveBeenCalledTimes(2);
    expect(getCandlesMock.mock.calls[1]).toEqual(["SPY", "1d", 500, "2026-01-05T00:00:00Z"]);
  });

  it("resets accumulated older candles when the base data object changes (symbol switch)", async () => {
    getCandlesMock.mockResolvedValue({
      symbol: "SPY",
      timeframe: "1d",
      candles: [candle("2026-01-04T00:00:00Z")],
      has_more: true,
      history_exhausted: false,
      next_before: "2026-01-04T00:00:00Z",
    } satisfies CandlesResponse);

    const { result, rerender } = renderHook(
      ({ base }: { base: AsyncResource<CandlesResponse> }) => useCandleHistoryPagination("SPY", "1d", base),
      { initialProps: { base: baseResource() } },
    );

    await act(async () => result.current.loadOlder());
    expect(result.current.candles).toHaveLength(3);

    // SPY panned back to 2018 -> switch to NVDA: a wholly new base `data`
    // object, unrelated to SPY's accumulated older pages.
    const nvdaBase: AsyncResource<CandlesResponse> = {
      state: "ready",
      error: null,
      data: {
        symbol: "NVDA",
        timeframe: "1d",
        candles: [candle("2026-02-01T00:00:00Z")],
        has_more: true,
        history_exhausted: false,
        next_before: "2026-02-01T00:00:00Z",
      },
    };
    rerender({ base: nvdaBase });

    expect(result.current.candles).toHaveLength(1);
    expect(result.current.candles[0].timestamp).toBe("2026-02-01T00:00:00Z");
    expect(result.current.loadingOlder).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("resets pagination state on a timeframe change (new base data object, same symbol)", () => {
    const { result, rerender } = renderHook(
      ({ base }: { base: AsyncResource<CandlesResponse> }) => useCandleHistoryPagination("SPY", "1d", base),
      { initialProps: { base: baseResource({ history_exhausted: true, has_more: false, next_before: null }) } },
    );
    expect(result.current.historyExhausted).toBe(true);

    const fiveMinBase = baseResource({
      timeframe: "5m",
      candles: [candle("2026-01-06T15:00:00Z")],
      has_more: true,
      history_exhausted: false,
      next_before: "2026-01-06T15:00:00Z",
    });
    rerender({ base: fiveMinBase });

    expect(result.current.historyExhausted).toBe(false);
    expect(result.current.candles).toHaveLength(1);
  });
});
