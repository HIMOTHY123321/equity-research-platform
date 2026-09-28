"use client";

import Link from "next/link";

import { GlossaryHint } from "@/components/GlossaryHint";
import { useSignalGate } from "@/hooks/useValidation";
import { formatSignalGateDecision, signalGateDecisionColorClass } from "@/lib/format";

/**
 * Phase 18 (§21/§22/§77); Phase 19 terminology fix: a compact terminal
 * widget, never a reproduction of the full Validation Lab. This is the
 * SIGNAL VALIDATION GATE (`app.validation.gate`, Decision/Alert signals)
 * -- deliberately called that and NOT "Forward Validation Gate", which is
 * a genuinely separate, independently-versioned gate scoped to Forecast
 * Lab (`app.forecasting.gate`). Both modules' own docstrings historically
 * used the same generic phrase, which is exactly the ambiguity this fix
 * removes at the UI layer (backend gate logic is unchanged). It is
 * deliberately GLOBAL (cross-symbol concentration limits mean it can
 * never validly pass for a single ticker -- see app.validation.gate) --
 * this widget states that explicitly rather than implying the
 * currently-viewed symbol was itself validated.
 */
export function ValidationStatusWidget() {
  const gate = useSignalGate("1h");

  if (gate.state === "loading") return <p className="text-[11px] text-muted">Loading validation status…</p>;
  if (gate.state === "error") return <p className="text-[11px] text-negative">{gate.error}</p>;
  const evaluation = gate.data;
  if (!evaluation) return null;

  return (
    <div className="space-y-1.5 text-[11px]">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-muted">
          Signal Validation Gate
          <GlossaryHint termId="signal-validation-gate" />
        </span>
        <span className={`font-mono font-semibold uppercase ${signalGateDecisionColorClass(evaluation.decision)}`}>
          {formatSignalGateDecision(evaluation.decision)}
        </span>
      </div>
      <p className="text-muted">
        Cross-symbol research qualification -- never scoped to a single ticker.
      </p>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted">
        <span>Resolved: {evaluation.raw_n}</span>
        <span>Independent episodes: {evaluation.independent_episode_count}</span>
        <span>Symbols: {evaluation.symbol_count}</span>
      </div>
      <Link href="/validation" className="inline-block text-accent hover:underline">
        OPEN VALIDATION LAB →
      </Link>
    </div>
  );
}
