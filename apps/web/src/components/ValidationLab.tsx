"use client";

import { useState } from "react";

import { GlossaryHint } from "@/components/GlossaryHint";
import {
  useHistoricalComparison,
  useProspectiveObservations,
  useSignalGate,
  useSignalGateHistory,
  useValidationCohort,
  useValidationStatus,
  useValidationSummary,
} from "@/hooks/useValidation";
import { formatExchangeTimestamp } from "@/lib/format";
import type { CohortStatistics } from "@/lib/types";

const EVENT_TYPES = [
  "entry_conditions_met",
  "thesis_strengthening",
  "thesis_weakening",
  "invalidated",
  "exit_conditions_met",
];

const EVENT_TYPE_PANELS: { eventType: string; title: string }[] = [
  { eventType: "entry_conditions_met", title: "ENTRY CONDITIONS" },
  { eventType: "thesis_strengthening", title: "STRENGTHENING" },
  { eventType: "thesis_weakening", title: "WEAKENING" },
  { eventType: "invalidated", title: "INVALIDATION" },
  { eventType: "exit_conditions_met", title: "EXIT" },
];

const DECISION_LABEL: Record<string, string> = {
  not_enough_data: "NOT ENOUGH DATA",
  fail: "FAIL",
  mixed: "MIXED",
  pass: "PASS",
};

const DECISION_STYLE: Record<string, string> = {
  not_enough_data: "text-muted",
  fail: "text-negative",
  mixed: "text-warning",
  pass: "text-positive",
};

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(0)}%`;
}

function num(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

function GateHeader() {
  const gate = useSignalGate("1h");
  const history = useSignalGateHistory(10);

  if (gate.state === "loading") return <p className="text-xs text-muted">Loading gate status…</p>;
  if (gate.state === "error") return <p className="text-xs text-negative">{gate.error}</p>;
  const evaluation = gate.data!;

  return (
    <section className="rounded-md border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 font-mono text-sm font-semibold text-foreground">
          FORWARD VALIDATION GATE
          <GlossaryHint termId="forward-validation-gate" />
        </h2>
        <span className={`font-mono text-sm font-bold uppercase ${DECISION_STYLE[evaluation.decision]}`}>
          {DECISION_LABEL[evaluation.decision]}
        </span>
      </div>
      <p className="mt-1 text-[11px] text-muted">
        Research qualification only -- never a BUY/SELL recommendation. Gate version {evaluation.gate_version}.
      </p>

      <div className="mt-3 grid grid-cols-2 gap-3 text-[11px] sm:grid-cols-4">
        <div>
          <div className="text-muted">Resolved observations</div>
          <div className="font-mono text-foreground">
            {evaluation.raw_n} / minimum {evaluation.criteria.min_independent_episodes}
          </div>
        </div>
        <div>
          <div className="text-muted">Independent episodes</div>
          <div className="font-mono text-foreground">{evaluation.independent_episode_count}</div>
        </div>
        <div>
          <div className="text-muted">Symbols</div>
          <div className="font-mono text-foreground">
            {evaluation.symbol_count} / minimum {evaluation.criteria.min_symbols}
          </div>
        </div>
        <div>
          <div className="text-muted">Observation duration</div>
          <div className="font-mono text-foreground">
            {evaluation.observation_days !== null ? `${evaluation.observation_days.toFixed(1)} days` : "—"} / minimum{" "}
            {evaluation.criteria.min_observation_days} days
          </div>
        </div>
      </div>

      {evaluation.reasons.length > 0 && (
        <ul className="mt-3 space-y-1 text-[11px] text-muted">
          {evaluation.reasons.map((reason) => (
            <li key={reason}>• {reason}</li>
          ))}
        </ul>
      )}

      <p className="mt-3 text-[10px] text-muted">
        Meeting the sample-size minimums above does not by itself guarantee PASS -- concentration, cost
        sensitivity, and effect stability are all evaluated separately.
      </p>

      {history.state === "ready" && history.data && history.data.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-[11px] text-muted">Gate history ({history.data.length})</summary>
          <ul className="mt-2 space-y-1 text-[11px]">
            {history.data.map((entry, i) => (
              <li key={i} className="text-muted">
                <span className={DECISION_STYLE[entry.decision]}>{DECISION_LABEL[entry.decision]}</span> —{" "}
                {entry.raw_n} observations, {entry.independent_episode_count} episodes, {entry.symbol_count} symbols
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function AIValidationSummary() {
  const summary = useValidationSummary({ timeframe: "1h", horizonBars: 5 });

  return (
    <section className="rounded-md border border-border bg-surface p-4">
      <h3 className="flex items-center gap-1.5 font-mono text-xs font-semibold text-foreground">
        AI VALIDATION SUMMARY
        <GlossaryHint termId="forward-validation-gate" />
      </h3>
      <p className="mt-1 text-[10px] text-muted">
        A plain-language recap of the deterministic figures above -- generated only from already-computed
        gate and cohort statistics, never from a live model call. No BUY/SELL, probability, or confidence
        language is ever produced.
      </p>
      {summary.state === "loading" && <p className="mt-2 text-[11px] text-muted">Generating…</p>}
      {summary.state === "error" && <p className="mt-2 text-[11px] text-negative">{summary.error}</p>}
      {summary.state === "ready" && summary.data && (
        <p className="mt-2 text-[11px] text-foreground">{summary.data.text}</p>
      )}
    </section>
  );
}

function ObservationMonitor() {
  const status = useValidationStatus();
  if (status.state !== "ready" || !status.data) return null;
  return (
    <section className="rounded-md border border-border bg-surface p-4 text-[11px]">
      <h3 className="font-mono text-xs font-semibold text-foreground">PROSPECTIVE OBSERVATIONS</h3>
      <div className="mt-2 flex gap-6">
        <div>
          <div className="text-muted">Total eligible</div>
          <div className="font-mono text-foreground">{status.data.total}</div>
        </div>
        <div>
          <div className="text-muted">Resolved</div>
          <div className="font-mono text-positive">{status.data.resolved}</div>
        </div>
        <div>
          <div className="text-muted">Unresolved (pending future data)</div>
          <div className="font-mono text-muted">{status.data.unresolved}</div>
        </div>
      </div>
    </section>
  );
}

function CohortStatsBody({ cohort }: { cohort: CohortStatistics }) {
  return (
    <div className="mt-3 space-y-2 text-[11px]">
      <div className="flex flex-wrap gap-4">
        <span>
          raw n <span className="font-mono text-foreground">{cohort.raw_n}</span>
        </span>
        <span>
          independent n <span className="font-mono text-foreground">{cohort.independent_n}</span>
        </span>
        <span>
          purged n <span className="font-mono text-foreground">{cohort.purged_n}</span>
        </span>
      </div>

      {cohort.raw_n === 0 ? (
        <p className="text-muted">NOT ENOUGH DATA for this cohort yet.</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-4">
            <span>
              median (5-bar) <span className="font-mono text-foreground">{num(cohort.median)}%</span>
            </span>
            <span>
              positive-return rate <span className="font-mono text-foreground">{pct(cohort.positive_rate)}</span>
            </span>
            <span>
              MFE (ATR) median <span className="font-mono text-foreground">{num(cohort.mfe_atr_median)}</span>
            </span>
            <span>
              MAE (ATR) median <span className="font-mono text-foreground">{num(cohort.mae_atr_median)}</span>
            </span>
            <span>
              invalidation rate <span className="font-mono text-foreground">{pct(cohort.invalidation_rate)}</span>
            </span>
          </div>

          {cohort.bootstrap_available && (
            <div>
              Bootstrap CI (median):{" "}
              <span className="font-mono text-foreground">
                {num(cohort.bootstrap_lower)}% .. {num(cohort.bootstrap_upper)}%
              </span>
            </div>
          )}

          {cohort.concentration_warnings.length > 0 && (
            <ul className="space-y-1 text-warning">
              {cohort.concentration_warnings.map((w) => (
                <li key={w.dimension}>⚠ {w.warning}</li>
              ))}
            </ul>
          )}

          <div>
            <div className="mb-1 flex items-center gap-1.5 text-muted">
              ESTIMATED COST SENSITIVITY (not actual fills)
              <GlossaryHint termId="cost-sensitivity" />
            </div>
            <table className="w-full max-w-md text-left font-mono text-[10px]">
              <thead>
                <tr className="text-muted">
                  <th className="pr-4">bps</th>
                  <th className="pr-4">median after cost</th>
                  <th>positive rate</th>
                </tr>
              </thead>
              <tbody>
                {cohort.cost_sensitivity.map((p) => (
                  <tr key={p.cost_bps}>
                    <td className="pr-4">{p.cost_bps}</td>
                    <td className="pr-4">{num(p.median_return_after_cost)}%</td>
                    <td>{pct(p.positive_rate_after_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function CohortExplorer() {
  const [eventType, setEventType] = useState(EVENT_TYPES[0]);
  const [symbol, setSymbol] = useState("");
  const cohort = useValidationCohort({
    eventType,
    horizonBars: 5,
    timeframe: "1h",
    symbol: symbol.trim() || undefined,
  });

  return (
    <section className="rounded-md border border-border bg-surface p-4">
      <h3 className="flex items-center gap-1.5 font-mono text-xs font-semibold text-foreground">
        COHORT EXPLORER
        <GlossaryHint termId="prospective-observation" />
      </h3>
      <p className="mt-1 text-[10px] text-muted">
        Ad-hoc symbol/event-type slicing. For the standing per-event-type breakdown, see Signal Research by
        Event Type below.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <select
          value={eventType}
          onChange={(e) => setEventType(e.target.value)}
          className="rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground"
        >
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          placeholder="Filter symbol (optional)"
          className="rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground"
        />
      </div>

      {cohort.state === "ready" && cohort.data && <CohortStatsBody cohort={cohort.data} />}
    </section>
  );
}

const EVENT_TYPE_GLOSSARY: Record<string, string> = {
  entry_conditions_met: "prospective-observation",
  thesis_strengthening: "prospective-observation",
  thesis_weakening: "prospective-observation",
  invalidated: "prospective-observation",
  exit_conditions_met: "prospective-observation",
};

function EventTypeResearchPanels() {
  // §3: dedicated, always-visible results for each Decision Engine event
  // type -- never collapsed into a single ad-hoc dropdown, so a low- or
  // zero-sample event type is just as visible as a well-sampled one.
  // Unrolled (not a .map() over a hook call) to keep the hook call count
  // and order fixed across renders, per the Rules of Hooks.
  const entry = useValidationCohort({ eventType: "entry_conditions_met", horizonBars: 5, timeframe: "1h" });
  const strengthening = useValidationCohort({
    eventType: "thesis_strengthening",
    horizonBars: 5,
    timeframe: "1h",
  });
  const weakening = useValidationCohort({ eventType: "thesis_weakening", horizonBars: 5, timeframe: "1h" });
  const invalidation = useValidationCohort({ eventType: "invalidated", horizonBars: 5, timeframe: "1h" });
  const exit = useValidationCohort({ eventType: "exit_conditions_met", horizonBars: 5, timeframe: "1h" });
  const cohorts = [entry, strengthening, weakening, invalidation, exit];

  const allWarnings = cohorts.flatMap((c, i) =>
    c.state === "ready" && c.data
      ? c.data.concentration_warnings.map((w) => ({ ...w, panel: EVENT_TYPE_PANELS[i].title }))
      : [],
  );

  const contradictions: string[] = [];
  const entryCohort = entry;
  const invalidationCohort = invalidation;
  if (
    entryCohort.state === "ready" &&
    entryCohort.data &&
    entryCohort.data.raw_n > 0 &&
    invalidationCohort.state === "ready" &&
    invalidationCohort.data &&
    invalidationCohort.data.raw_n > 0
  ) {
    const entryMedian = entryCohort.data.median;
    const invalidationRate = entryCohort.data.invalidation_rate;
    if (entryMedian !== null && entryMedian > 0 && invalidationRate !== null && invalidationRate > 0.5) {
      contradictions.push(
        `Entry-conditions-met median return is positive (${num(entryMedian)}%) but more than half of ` +
          `those observations also invalidated (${pct(invalidationRate)}) -- a positive average return can ` +
          `still coexist with a majority-invalidation outcome; this is not itself a bug, but should not be ` +
          `read as "entries reliably work."`,
      );
    }
  }

  return (
    <section className="rounded-md border border-border bg-surface p-4">
      <h3 className="flex items-center gap-1.5 font-mono text-xs font-semibold text-foreground">
        SIGNAL RESEARCH BY EVENT TYPE
        <GlossaryHint termId="prospective-observation" />
      </h3>
      <p className="mt-1 text-[10px] text-muted">
        5-bar horizon, 1h timeframe, all symbols. Each panel is independent -- a well-sampled Entry panel does
        not imply anything about the Invalidation panel&apos;s own sample size.
      </p>

      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {EVENT_TYPE_PANELS.map(({ eventType, title }, i) => {
          const cohort = cohorts[i];
          return (
            <div key={eventType} className="rounded border border-border/60 p-3">
              <h4 className="flex items-center gap-1.5 font-mono text-[11px] font-semibold text-foreground">
                {title}
                <GlossaryHint termId={EVENT_TYPE_GLOSSARY[eventType]} />
              </h4>
              {cohort.state === "loading" && <p className="mt-2 text-[11px] text-muted">Loading…</p>}
              {cohort.state === "error" && <p className="mt-2 text-[11px] text-negative">{cohort.error}</p>}
              {cohort.state === "ready" && cohort.data && <CohortStatsBody cohort={cohort.data} />}
            </div>
          );
        })}
      </div>

      <div className="mt-4 border-t border-border/60 pt-3">
        <h4 className="font-mono text-[11px] font-semibold text-foreground">CONCENTRATION &amp; CONTRADICTIONS</h4>
        {allWarnings.length === 0 && contradictions.length === 0 ? (
          <p className="mt-1 text-[11px] text-muted">No concentration warnings or contradictions detected yet.</p>
        ) : (
          <div className="mt-2 space-y-2 text-[11px]">
            {allWarnings.length > 0 && (
              <ul className="space-y-1 text-warning">
                {allWarnings.map((w, i) => (
                  <li key={i}>
                    ⚠ [{w.panel}] {w.warning}
                  </li>
                ))}
              </ul>
            )}
            {contradictions.length > 0 && (
              <ul className="space-y-1 text-warning">
                {contradictions.map((c, i) => (
                  <li key={i}>⚠ {c}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function HistoricalVsProspective() {
  const [symbol, setSymbol] = useState("SPY");
  const [setupType, setSetupType] = useState("breakout_retest");
  const [direction, setDirection] = useState("bullish");
  const comparison = useHistoricalComparison({ symbol, setupType, direction, horizonBars: 5 });

  return (
    <section className="rounded-md border border-border bg-surface p-4">
      <h3 className="flex items-center gap-1.5 font-mono text-xs font-semibold text-foreground">
        HISTORICAL VS PROSPECTIVE
        <GlossaryHint termId="historical-vs-prospective" />
      </h3>
      <div className="mt-2 flex flex-wrap gap-2">
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          className="w-24 rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground"
        />
        <input
          value={setupType}
          onChange={(e) => setSetupType(e.target.value)}
          className="w-40 rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground"
        />
        <select
          value={direction}
          onChange={(e) => setDirection(e.target.value)}
          className="rounded border border-border bg-background px-2 py-1 text-[11px] text-foreground"
        >
          <option value="bullish">bullish</option>
          <option value="bearish">bearish</option>
        </select>
      </div>

      {comparison.state === "ready" && comparison.data && (
        <div className="mt-3 text-[11px]">
          {comparison.data.note ? (
            <p className="text-muted">{comparison.data.note}</p>
          ) : (
            <div className="flex flex-wrap gap-6">
              <span>
                historical n <span className="font-mono text-foreground">{comparison.data.historical_n}</span> · median{" "}
                <span className="font-mono text-foreground">{num(comparison.data.historical_median_effect)}%</span>
              </span>
              <span>
                prospective n <span className="font-mono text-foreground">{comparison.data.prospective_n}</span> · median{" "}
                <span className="font-mono text-foreground">{num(comparison.data.prospective_median_effect)}%</span>
              </span>
              <span>
                direction agreement{" "}
                <span className="font-mono text-foreground">
                  {comparison.data.direction_agreement === null ? "—" : comparison.data.direction_agreement ? "yes" : "no"}
                </span>
              </span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function ValidationLab() {
  const observations = useProspectiveObservations({ resolvedOnly: false });

  return (
    <div className="space-y-4">
      <GateHeader />
      <AIValidationSummary />
      <ObservationMonitor />
      <EventTypeResearchPanels />
      <CohortExplorer />
      <HistoricalVsProspective />

      {observations.state === "ready" && observations.data && observations.data.length > 0 && (
        <section className="rounded-md border border-border bg-surface p-4">
          <h3 className="font-mono text-xs font-semibold text-foreground">RECENT PROSPECTIVE OBSERVATIONS</h3>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left font-mono text-[10px]">
              <thead>
                <tr className="text-muted">
                  <th className="pr-4">Symbol</th>
                  <th className="pr-4">Event</th>
                  <th className="pr-4">Occurred</th>
                  <th className="pr-4">Resolved</th>
                  <th>5-bar return</th>
                </tr>
              </thead>
              <tbody>
                {observations.data.slice(0, 25).map((o) => (
                  <tr key={o.observation_id} className="border-t border-border/60">
                    <td className="pr-4 text-foreground">{o.symbol}</td>
                    <td className="pr-4 text-muted">{o.event_type.replace(/_/g, " ")}</td>
                    <td className="pr-4 text-muted">{formatExchangeTimestamp(o.alert_occurred_at)}</td>
                    <td className="pr-4">{o.resolved ? "yes" : "pending"}</td>
                    <td>{o.return_5 !== null ? `${o.return_5.toFixed(2)}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
