import { notFound } from "next/navigation";

import { LiveSimulatorClient } from "./LiveSimulatorClient";

/**
 * Phase 17 (§60/§79/§99): a server component wrapper so the guard runs
 * BEFORE any client bundle for this page is even reachable -- `notFound()`
 * here renders the app's not-found boundary and never ships
 * LiveSimulatorClient's markup, regardless of what the backend does. This
 * is the frontend half of "impossible to reach in production"; the
 * backend half is /api/dev/live-simulator 404ing unless
 * ENABLE_DEV_LIVE_SIMULATOR is set (see app.api.routes.dev_live) --
 * belt and suspenders, neither alone is trusted.
 */
export default function DevLiveSimulatorPage() {
  if (process.env.NODE_ENV === "production") {
    notFound();
  }
  return <LiveSimulatorClient />;
}
