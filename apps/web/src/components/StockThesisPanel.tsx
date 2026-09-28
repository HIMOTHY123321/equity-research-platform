"use client";

import { useRef, useState } from "react";

import { GlossaryHint } from "@/components/GlossaryHint";
import { Block, Row } from "@/components/PanelPrimitives";
import { ApiError, getStockThesis } from "@/lib/api";
import { formatDecisionState, formatEnumLabel, formatExchangeTimestamp } from "@/lib/format";
import type { StockThesis, Timeframe } from "@/lib/types";

type Status = "idle" | "running" | "completed" | "failed";

const RESEARCH_LEAN_LABEL: Record<string, string> = {
  bullish_lean: "BULLISH LEAN",
  bearish_lean: "BEARISH LEAN",
  mixed: "MIXED",
  insufficient_evidence: "INSUFFICIENT EVIDENCE",
  abstain: "ABSTAIN",
};

const HISTORY_LABEL: Record<string, string> = {
  full: "FULL",
  adequate: "ADEQUATE",
  limited: "LIMITED",
  very_limited: "VERY LIMITED TRADING HISTORY",
  insufficient: "INSUFFICIENT HISTORY",
};

/**
 * Phase 19 (Part 3/§9): "Analyze This Stock" -- a prominent action, not an
 * auto-loaded-on-every-render panel (Part 11: the composed thesis calls
 * app.thesis.service, which itself composes catalyst/analog/research work
 * that is genuinely expensive; gating it behind a click keeps every other
 * page load cheap, the same convention AnalogSearchButton already uses).
 * Every field rendered here comes straight off StockThesis -- nothing is
 * computed or reworded client-side.
 */
export function StockThesisPanel({ symbol, timeframe }: { symbol: string; timeframe: Timeframe }) {
  // Remounting on symbol/timeframe change resets every piece of local
  // state below for free (no effect-driven reset needed, and no risk of a
  // stale symbol's thesis staying on screen after a switch).
  return <StockThesisPanelInner key={`${symbol}_${timeframe}`} symbol={symbol} timeframe={timeframe} />;
}

function StockThesisPanelInner({ symbol, timeframe }: { symbol: string; timeframe: Timeframe }) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [thesis, setThesis] = useState<StockThesis | null>(null);
  const requestToken = useRef(0);

  async function handleClick() {
    if (status === "running") return;
    if (thesis) {
      setThesis(null);
      setStatus("idle");
      return;
    }
    const token = ++requestToken.current;
    setStatus("running");
    setError(null);
    try {
      const result = await getStockThesis(symbol, timeframe);
      if (requestToken.current !== token) return; // a newer request/symbol switch won this race
      setThesis(result);
      setStatus("completed");
    } catch (err) {
      if (requestToken.current !== token) return;
      setError(err instanceof ApiError ? err.message : "Stock Thesis could not be composed");
      setStatus("failed");
    }
  }

  return (
    <section className="rounded-md border border-border bg-surface p-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-semibold tracking-wide text-foreground">STOCK THESIS — {symbol}</h2>
        <button
          type="button"
          onClick={handleClick}
          disabled={status === "running"}
          className="rounded border border-accent px-2.5 py-1 font-mono text-[10px] font-semibold text-accent disabled:opacity-50"
        >
          {status === "running" ? "ANALYZING…" : thesis ? "HIDE STOCK THESIS" : "ANALYZE THIS STOCK"}
        </button>
      </div>
      {status === "failed" && error && <p className="text-[11px] text-negative">{error}</p>}
      {thesis && <StockThesisBody thesis={thesis} />}
    </section>
  );
}

function StockThesisBody({ thesis }: { thesis: StockThesis }) {
  const leanLabel = RESEARCH_LEAN_LABEL[thesis.research_lean] ?? thesis.research_lean.toUpperCase();
  return (
    <div className="space-y-3">
      <div className="text-[11px] text-muted">
        As of {formatExchangeTimestamp(thesis.as_of)} via {thesis.market_data_provider}
        {thesis.session ? ` · session: ${formatEnumLabel(thesis.session)}` : ""}
      </div>

      <Block title={<span className="flex items-center gap-1">CURRENT RESEARCH LEAN <GlossaryHint termId="research-lean" /></span>}>
        <p className="font-mono text-sm font-semibold text-foreground">{leanLabel}</p>
        <ul className="mt-1 list-inside list-disc text-[11px] text-muted">
          {thesis.research_lean_reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      </Block>

      <Block title="MULTI-TIMEFRAME TREND">
        <div className="space-y-1.5">
          {thesis.multi_timeframe_trend.map((row) => (
            <div key={row.timeframe} className="border-b border-border pb-1 last:border-0">
              <Row
                label={row.timeframe.toUpperCase()}
                value={`${formatEnumLabel(row.trend)}${row.strength ? ` (${formatEnumLabel(row.strength)})` : ""}`}
              />
              {row.explanation.length > 0 && (
                <p className="text-[11px] text-muted">{row.explanation.join("; ")}</p>
              )}
            </div>
          ))}
        </div>
      </Block>

      <Block title="DECISION STATE">
        {thesis.decision_plan ? (
          <>
            <Row label="State" value={formatDecisionState(thesis.decision_plan.state)} />
            <Row label="Setup" value={`${thesis.decision_plan.setup_type} ${thesis.decision_plan.direction}`} />
          </>
        ) : (
          <p className="text-[11px] text-muted">No open DecisionPlan exists for this symbol/timeframe yet.</p>
        )}
      </Block>

      {thesis.key_levels.length > 0 && (
        <Block title="KEY LEVELS">
          {thesis.key_levels.map((level, i) => (
            <Row
              key={i}
              label={`${level.is_nearest ? "Nearest " : ""}${formatEnumLabel(level.kind)}`}
              value={`${level.price.toFixed(2)} (${level.source_count} sources, ${level.timeframe_count} timeframes)`}
            />
          ))}
        </Block>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Block title="BULL CASE">
          {thesis.evidence_for.length > 0 ? (
            <ul className="list-inside list-disc text-[11px] text-positive">
              {thesis.evidence_for.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] text-muted">No supporting evidence found.</p>
          )}
        </Block>
        <Block title="BEAR CASE">
          {thesis.evidence_against.length > 0 ? (
            <ul className="list-inside list-disc text-[11px] text-negative">
              {thesis.evidence_against.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] text-muted">No opposing evidence found.</p>
          )}
        </Block>
      </div>

      {thesis.contradictions.length > 0 && (
        <Block title="CONTRADICTIONS">
          <ul className="list-inside list-disc text-[11px] text-amber-600 dark:text-amber-400">
            {thesis.contradictions.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </Block>
      )}

      {(thesis.catalyst_context || thesis.nearest_catalyst_event) && (
        <Block title="CATALYSTS">
          {thesis.nearest_catalyst_event ? (
            <p className="text-[11px] text-muted">
              Relevant catalyst context: {thesis.nearest_catalyst_event.title}
            </p>
          ) : (
            <p className="text-[11px] text-muted">No relevant catalyst context found.</p>
          )}
        </Block>
      )}

      <Block title={<span className="flex items-center gap-1">HISTORICAL ANALOGS <GlossaryHint termId="historical-analog" /></span>}>
        <p className="text-[10px] italic text-muted">Historical analogs are context, not predictions.</p>
        {thesis.historical_analogs && thesis.historical_analogs.analogs.length > 0 ? (
          <ul className="mt-1 list-inside list-disc text-[11px] text-foreground">
            {thesis.historical_analogs.analogs.slice(0, 5).map((analog, i) => (
              <li key={i}>
                {analog.symbol} — {formatExchangeTimestamp(analog.timestamp)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[11px] text-muted">No historical analogs available.</p>
        )}
      </Block>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Block title={<span className="flex items-center gap-1">SIGNAL VALIDATION <GlossaryHint termId="signal-validation-gate" /></span>}>
          <Row label="Decision" value={formatEnumLabel(thesis.signal_validation.decision)} />
          {thesis.signal_validation.reasons.map((reason, i) => (
            <p key={i} className="text-[11px] text-muted">{reason}</p>
          ))}
        </Block>
        <Block title={<span className="flex items-center gap-1">RANKING VALIDATION <GlossaryHint termId="validated-relative-ranking" /></span>}>
          <p className="font-mono text-[11px] font-semibold text-amber-600 dark:text-amber-400">
            {thesis.ranking_validation_message}
          </p>
        </Block>
      </div>

      {(thesis.strengthens_if.length > 0 || thesis.weakens_if.length > 0 || thesis.invalidation.length > 0) && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {thesis.strengthens_if.length > 0 && (
            <Block title="WHAT WOULD STRENGTHEN">
              <ul className="list-inside list-disc text-[11px] text-positive">
                {thesis.strengthens_if.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </Block>
          )}
          {thesis.weakens_if.length > 0 && (
            <Block title="WHAT WOULD WEAKEN">
              <ul className="list-inside list-disc text-[11px] text-amber-600 dark:text-amber-400">
                {thesis.weakens_if.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </Block>
          )}
          {thesis.invalidation.length > 0 && (
            <Block title="INVALIDATION">
              <ul className="list-inside list-disc text-[11px] text-negative">
                {thesis.invalidation.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </Block>
          )}
        </div>
      )}

      <Block title="DATA & HISTORY LIMITATIONS">
        <p className="text-[11px] text-foreground">
          {HISTORY_LABEL[thesis.history_sufficiency] ?? thesis.history_sufficiency.toUpperCase()}
        </p>
        <p className="text-[11px] text-muted">{thesis.history_sufficiency_reason}</p>
        <p className="mt-1 text-[11px] text-muted">{thesis.fundamentals_status}</p>
        {thesis.data_limitations.map((item, i) => (
          <p key={i} className="text-[11px] text-muted">{item}</p>
        ))}
      </Block>
    </div>
  );
}
