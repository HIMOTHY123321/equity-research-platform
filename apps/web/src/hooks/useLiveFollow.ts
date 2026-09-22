"use client";

import { useCallback, useState } from "react";

/**
 * MARKET UX COMPLETION PASS (#6): live-follow state machine for REAL TIME
 * mode. True end-to-end streaming behavior (chart visually snapping to a
 * genuinely-arriving forming candle) cannot be verified without a real
 * Massive entitlement, which is not active in this environment -- this
 * hook is the architecture piece that makes the eventual wiring a one-line
 * change (pass `autoFollow` into the chart's live-candle prop) rather than
 * a rewrite, and is fully covered by mocked unit tests instead.
 *
 * Rules:
 * - `autoFollow` starts true whenever REAL TIME genuinely activates.
 * - Calling `pause()` (the caller wires this to "user manually panned the
 *   chart") stops auto-follow -- new events may keep arriving in the
 *   background without snapping the view away from what the user is
 *   inspecting.
 * - Calling `resume()` ("RETURN TO LIVE" clicked) re-enables it.
 * - If `streamingActive` is false (yfinance, or entitlement lost),
 *   `autoFollow` reads as true regardless of the stored paused state --
 *   there is no "paused" state that means anything without genuine
 *   streaming to pause. This is a pure derivation (no effect needed): the
 *   underlying paused flag is preserved, so if streaming comes back later
 *   in the same session the prior pause is simply forgotten, never
 *   resurrected mid-render.
 */
export function useLiveFollow(streamingActive: boolean) {
  const [pausedByUser, setPausedByUser] = useState(false);
  const autoFollow = !streamingActive || !pausedByUser;

  const pause = useCallback(() => {
    if (streamingActive) setPausedByUser(true);
  }, [streamingActive]);

  const resume = useCallback(() => setPausedByUser(false), []);

  return {
    autoFollow,
    /** True only when the caller should show a "RETURN TO LIVE" control. */
    showReturnToLive: streamingActive && pausedByUser,
    pause,
    resume,
  };
}
