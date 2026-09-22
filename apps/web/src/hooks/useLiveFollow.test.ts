import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useLiveFollow } from "./useLiveFollow";

/**
 * (#6) Genuine Massive streaming cannot be exercised in this environment --
 * these tests mock `streamingActive` and simulate pan/return-to-live
 * events directly against the hook's state machine, proving the
 * architecture is correct without claiming real streaming verification.
 */
describe("useLiveFollow (#6: mocked live-follow architecture)", () => {
  it("starts with autoFollow true", () => {
    const { result } = renderHook(() => useLiveFollow(true));
    expect(result.current.autoFollow).toBe(true);
    expect(result.current.showReturnToLive).toBe(false);
  });

  it("pause() stops auto-follow and shows RETURN TO LIVE, only when streaming is active", () => {
    const { result } = renderHook(() => useLiveFollow(true));
    act(() => result.current.pause());
    expect(result.current.autoFollow).toBe(false);
    expect(result.current.showReturnToLive).toBe(true);
  });

  it("resume() re-enables auto-follow and hides RETURN TO LIVE", () => {
    const { result } = renderHook(() => useLiveFollow(true));
    act(() => result.current.pause());
    act(() => result.current.resume());
    expect(result.current.autoFollow).toBe(true);
    expect(result.current.showReturnToLive).toBe(false);
  });

  it("pause() is a no-op when streaming is not active (yfinance)", () => {
    const { result } = renderHook(() => useLiveFollow(false));
    act(() => result.current.pause());
    expect(result.current.autoFollow).toBe(true);
    expect(result.current.showReturnToLive).toBe(false);
  });

  it("never shows RETURN TO LIVE when streaming is inactive, even if somehow paused", () => {
    const { result, rerender } = renderHook(({ streaming }) => useLiveFollow(streaming), {
      initialProps: { streaming: true },
    });
    act(() => result.current.pause());
    expect(result.current.showReturnToLive).toBe(true);

    // Streaming capability drops mid-session (e.g. entitlement lost).
    rerender({ streaming: false });
    expect(result.current.autoFollow).toBe(true);
    expect(result.current.showReturnToLive).toBe(false);
  });

  it("forces autoFollow back to true when streaming capability turns off", () => {
    const { result, rerender } = renderHook(({ streaming }) => useLiveFollow(streaming), {
      initialProps: { streaming: true },
    });
    act(() => result.current.pause());
    expect(result.current.autoFollow).toBe(false);

    rerender({ streaming: false });
    expect(result.current.autoFollow).toBe(true);
  });
});
