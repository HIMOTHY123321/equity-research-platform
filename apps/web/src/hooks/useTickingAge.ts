"use client";

import { useEffect, useState } from "react";

/**
 * MARKET EXPERIENCE COMPLETION PASS (#3): the freshness AGE must visibly
 * advance every second in the browser, independent of how often a new
 * quote/poll/WS message actually arrives -- the backend's own
 * `freshness.age_seconds` is a snapshot computed at send time and never
 * changes between messages, which is what made the age counter look frozen.
 *
 * `Date.now()` must never run during render (React Compiler purity rule) --
 * it's called only inside the effect's timer callbacks, which store the
 * elapsed milliseconds in state; the initial tick is deferred with a 0ms
 * timeout so no setState call happens synchronously within the effect body
 * either. The price and source timestamp themselves are never touched
 * here -- only the elapsed-time display ticks; a genuine new event
 * changing `sourceTimestamp` resets the age to that event's own true age.
 */
export function useTickingAgeSeconds(sourceTimestamp: string | null): number | null {
  const [ageMs, setAgeMs] = useState<number | null>(null);

  useEffect(() => {
    if (!sourceTimestamp) return;
    const sourceMs = new Date(sourceTimestamp).getTime();
    const update = () => setAgeMs(Date.now() - sourceMs);
    const initialTick = setTimeout(update, 0);
    const interval = setInterval(update, 1000);
    return () => {
      clearTimeout(initialTick);
      clearInterval(interval);
    };
  }, [sourceTimestamp]);

  if (!sourceTimestamp) return null;
  return ageMs === null ? null : ageMs / 1000;
}
