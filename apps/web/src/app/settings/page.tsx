"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { TopNav } from "@/components/TopNav";
import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  disableMonitoring,
  enableMonitoring,
  getAlertPreferences,
  getLiveStatus,
  getMyPlan,
  getSystemStatus,
  listMonitoring,
  setAlertPreference,
  type PlanOut,
  type SystemStatus,
} from "@/lib/api";
import type { AlertPreference, LiveStatusResponse, MonitoringSubscription } from "@/lib/types";

const ALERT_TYPE_LABELS: Record<string, string> = {
  plan_created: "Plan created",
  watching: "Watching",
  entry_conditions_met: "Entry conditions met",
  thesis_activated: "Thesis activated",
  thesis_strengthening: "Thesis strengthening",
  thesis_weakening: "Thesis weakening",
  invalidated: "Invalidated",
  exit_conditions_met: "Exit conditions met",
  expired: "Expired",
  condition_passed: "Condition passed",
  condition_failed: "Condition failed",
  conflict_added: "Conflict added",
  conflict_removed: "Conflict removed",
  catalyst_update: "Catalyst update",
  data_stale: "Data stale",
  data_recovered: "Data recovered",
  stream_disconnected: "Stream disconnected",
  stream_reconnected: "Stream reconnected",
};

/**
 * Phase 16.1 (§9): account/session/preferences/monitoring/provider-
 * status/plan, all in one place. Every section reads from and writes to
 * strictly THIS user's own data -- no admin surface, no secrets rendered
 * (never the JWT, never an API key).
 */
export default function SettingsPage() {
  const router = useRouter();
  const { user, logout } = useAuth();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logout();
      router.push("/login");
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-6 py-6">
        <h1 className="font-mono text-lg font-semibold">Settings</h1>

        <Section title="Account">
          {user ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
              <dt className="text-muted">Email</dt>
              <dd>{user.email}</dd>
              <dt className="text-muted">Status</dt>
              <dd>{user.status}</dd>
              <dt className="text-muted">Member since</dt>
              <dd>{new Date(user.created_at).toLocaleDateString()}</dd>
            </dl>
          ) : (
            <p className="text-xs text-muted">Loading…</p>
          )}
        </Section>

        <Section title="Session">
          <button
            type="button"
            onClick={handleSignOut}
            disabled={signingOut}
            className="rounded-md border border-border px-3 py-1.5 text-xs hover:border-negative hover:text-negative disabled:opacity-60"
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </Section>

        <PlanSection />
        <ProviderStatusSection />
        <AlertPreferencesSection />
        <MonitoringSection />
      </main>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-border bg-surface p-4">
      <h2 className="mb-3 font-mono text-xs font-semibold uppercase tracking-wide text-muted">{title}</h2>
      {children}
    </section>
  );
}

function PlanSection() {
  const [plan, setPlan] = useState<PlanOut | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    getMyPlan()
      .then((p) => {
        if (!cancelled) {
          setPlan(p);
          setState("ready");
        }
      })
      .catch(() => !cancelled && setState("error"));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Section title="Plan">
      {state === "loading" && <p className="text-xs text-muted">Loading…</p>}
      {state === "error" && <p className="text-xs text-negative">Failed to load plan.</p>}
      {state === "ready" && plan && (
        <div className="text-xs">
          <p className="mb-2">
            Current plan: <span className="font-semibold uppercase">{plan.plan}</span>
          </p>
          {plan.entitlements.length > 0 ? (
            <ul className="list-inside list-disc text-muted">
              {plan.entitlements.map((e) => (
                <li key={e}>{e.replace(/_/g, " ")}</li>
              ))}
            </ul>
          ) : (
            <p className="text-muted">No additional entitlements on this plan.</p>
          )}
          <p className="mt-2 text-[10px] text-muted">
            Test-mode only -- no payment provider is connected. Plan changes require an administrator.
          </p>
        </div>
      )}
    </Section>
  );
}

const ENTITLEMENT_LABELS: Record<string, string> = {
  entitled: "Entitled",
  not_entitled: "Not entitled",
  unknown: "Unknown (unconfirmed)",
  misconfigured: "Misconfigured",
};

function ProviderStatusSection() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [liveStatus, setLiveStatus] = useState<LiveStatusResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSystemStatus().then((s) => !cancelled && setStatus(s));
    getLiveStatus()
      .then((s) => !cancelled && setLiveStatus(s))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!status) return <Section title="Provider status">{<p className="text-xs text-muted">Loading…</p>}</Section>;

  return (
    <Section title="Provider status">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
        <dt className="text-muted">Market data</dt>
        <dd>
          {status.market_data.provider}
          {status.market_data.development_only_fallback_in_use && (
            <span className="ml-2 text-[10px] text-warning">development-only fallback</span>
          )}
        </dd>
        <dt className="text-muted">News</dt>
        <dd>
          {status.news.provider}
          {status.news.development_only_fallback_in_use && (
            <span className="ml-2 text-[10px] text-warning">development-only fallback</span>
          )}
        </dd>
        <dt className="text-muted">AI analysis</dt>
        <dd>{status.ai_analysis.provider}</dd>
        <dt className="text-muted">Environment</dt>
        <dd>{status.environment}</dd>
        {liveStatus && (
          <>
            <dt className="text-muted">Streaming entitlement</dt>
            <dd>
              {ENTITLEMENT_LABELS[liveStatus.entitlement.status] ?? liveStatus.entitlement.status}
              <span className="ml-2 text-[10px] text-muted">({liveStatus.entitlement.reason})</span>
            </dd>
            <dt className="text-muted">Real-time data</dt>
            <dd>
              {liveStatus.real_time_available ? (
                <span className="text-positive">Available</span>
              ) : (
                <span className="text-muted">Not available -- showing latest available data only</span>
              )}
            </dd>
          </>
        )}
      </dl>
    </Section>
  );
}

function AlertPreferencesSection() {
  const [prefs, setPrefs] = useState<AlertPreference[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    getAlertPreferences()
      .then((p) => {
        if (!cancelled) {
          setPrefs(p);
          setState("ready");
        }
      })
      .catch(() => !cancelled && setState("error"));
    return () => {
      cancelled = true;
    };
  }, []);

  async function toggle(alertType: string, enabled: boolean) {
    setPrefs((prev) => prev.map((p) => (p.alert_type === alertType ? { ...p, enabled } : p)));
    try {
      await setAlertPreference(alertType, enabled);
    } catch (err) {
      setPrefs((prev) => prev.map((p) => (p.alert_type === alertType ? { ...p, enabled: !enabled } : p)));
      void (err instanceof ApiError ? err.message : err);
    }
  }

  return (
    <Section title="Alert preferences">
      {state === "loading" && <p className="text-xs text-muted">Loading…</p>}
      {state === "error" && <p className="text-xs text-negative">Failed to load preferences.</p>}
      {state === "ready" && (
        <ul className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          {prefs.map((p) => (
            <li key={p.alert_type} className="flex items-center justify-between gap-2">
              <span>{ALERT_TYPE_LABELS[p.alert_type] ?? p.alert_type}</span>
              <button
                type="button"
                role="switch"
                aria-checked={p.enabled}
                aria-label={`${p.enabled ? "Disable" : "Enable"} ${ALERT_TYPE_LABELS[p.alert_type] ?? p.alert_type} alerts`}
                onClick={() => toggle(p.alert_type, !p.enabled)}
                className={`h-4 w-8 rounded-full transition-colors ${p.enabled ? "bg-accent" : "bg-border"}`}
              >
                <span
                  className={`block h-3 w-3 rounded-full bg-background transition-transform ${
                    p.enabled ? "translate-x-4" : "translate-x-0.5"
                  }`}
                />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function MonitoringSection() {
  const [subs, setSubs] = useState<MonitoringSubscription[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  async function load() {
    try {
      const data = await listMonitoring();
      setSubs(data);
      setState("ready");
    } catch {
      setState("error");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);

  async function toggle(symbol: string, enabled: boolean) {
    setSubs((prev) => prev.map((s) => (s.symbol === symbol ? { ...s, enabled } : s)));
    try {
      if (enabled) await enableMonitoring(symbol);
      else await disableMonitoring(symbol);
    } catch {
      await load();
    }
  }

  return (
    <Section title="Monitoring subscriptions">
      <p className="mb-2 text-[10px] text-muted">
        Which symbols you receive alerts for -- independent of your Watchlist. Manage per-symbol monitoring from
        the Watchlist sidebar; enabled subscriptions are listed here.
      </p>
      {state === "loading" && <p className="text-xs text-muted">Loading…</p>}
      {state === "error" && <p className="text-xs text-negative">Failed to load monitoring subscriptions.</p>}
      {state === "ready" && subs.length === 0 && (
        <p className="text-xs text-muted">Not monitoring any symbols yet.</p>
      )}
      {state === "ready" && subs.length > 0 && (
        <ul className="space-y-1 text-xs">
          {subs.map((s) => (
            <li key={s.symbol} className="flex items-center justify-between">
              <span className="font-mono">{s.symbol}</span>
              <button
                type="button"
                role="switch"
                aria-checked={s.enabled}
                aria-label={`${s.enabled ? "Stop" : "Start"} monitoring ${s.symbol}`}
                onClick={() => toggle(s.symbol, !s.enabled)}
                className={`h-4 w-8 rounded-full transition-colors ${s.enabled ? "bg-accent" : "bg-border"}`}
              >
                <span
                  className={`block h-3 w-3 rounded-full bg-background transition-transform ${
                    s.enabled ? "translate-x-4" : "translate-x-0.5"
                  }`}
                />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
