"use client";

import { useState } from "react";

import { ApiError, getEvidencePacket, postResearchBrief } from "@/lib/api";
import type { AnalysisMode, EvidencePacket, ResearchBrief, SetupCandidate } from "@/lib/types";

type Status = "idle" | "loading" | "loaded" | "failed";

const MODES: { value: AnalysisMode; label: string }[] = [
  { value: "quick", label: "QUICK" },
  { value: "full", label: "FULL" },
  { value: "why_this_setup", label: "WHY THIS SETUP" },
  { value: "why_not", label: "WHY NOT" },
  { value: "catalyst", label: "CATALYST" },
  { value: "analogs", label: "ANALOGS" },
];

function TextBlock({ title, text }: { title: string; text: string }) {
  if (!text) return null;
  return (
    <div>
      <h5 className="text-[10px] font-semibold tracking-wide text-muted">{title}</h5>
      <p className="mt-0.5 text-[11px] text-foreground">{text}</p>
    </div>
  );
}

function ListBlock({ title, items, itemClassName }: { title: string; items: string[]; itemClassName?: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h5 className="text-[10px] font-semibold tracking-wide text-muted">{title}</h5>
      <ul className="mt-0.5 space-y-0.5">
        {items.map((item, idx) => (
          <li key={idx} className={`text-[11px] ${itemClassName ?? "text-foreground"}`}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Phase 11 (#M): institutional-style AI research analyst -- not a chatbot.
 * The AI is strictly downstream of the deterministic EvidencePacket; this
 * panel only ever renders a server-validated ResearchBrief and the packet
 * it was grounded against. Click-to-load, same discipline as
 * CatalystContextCard/AnalogSearchButton -- no always-on network call.
 */
export function AIResearchAnalystPanel({ candidate }: { candidate: SetupCandidate }) {
  const [status, setStatus] = useState<Status>("idle");
  const [mode, setMode] = useState<AnalysisMode>("full");
  const [brief, setBrief] = useState<ResearchBrief | null>(null);
  const [packet, setPacket] = useState<EvidencePacket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showPacket, setShowPacket] = useState(false);

  async function loadMode(nextMode: AnalysisMode) {
    setMode(nextMode);
    setStatus("loading");
    setError(null);
    try {
      const [briefResult, packetResult] = await Promise.all([
        postResearchBrief({
          symbol: candidate.symbol,
          timeframe: candidate.timeframe,
          setupId: candidate.id,
          mode: nextMode,
        }),
        getEvidencePacket({ symbol: candidate.symbol, timeframe: candidate.timeframe, setupId: candidate.id }),
      ]);
      setBrief(briefResult);
      setPacket(packetResult);
      setStatus("loaded");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "AI Research Analyst is unavailable");
      setStatus("failed");
    }
  }

  async function toggle() {
    if (status === "loading") return;
    if (brief) {
      setBrief(null);
      setPacket(null);
      setStatus("idle");
      return;
    }
    await loadMode(mode);
  }

  return (
    <div className="mt-2 border-t border-border pt-2">
      <button
        type="button"
        onClick={toggle}
        disabled={status === "loading"}
        className="rounded border border-accent px-2.5 py-1 font-mono text-[10px] font-semibold text-accent disabled:opacity-50"
      >
        {status === "loading" ? "ANALYZING…" : brief ? "HIDE AI RESEARCH ANALYST" : "AI RESEARCH ANALYST"}
      </button>

      {status === "failed" && error && <p className="mt-1 text-[11px] text-negative">{error}</p>}

      {brief && (
        <div className="mt-2 rounded border border-border bg-surface-raised p-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h5 className="text-[10px] font-semibold tracking-wide text-muted">AI RESEARCH ANALYST</h5>
            <span className="rounded bg-border px-1.5 py-0.5 text-[9px] uppercase text-muted">
              {brief.provider}
              {brief.model ? ` · ${brief.model}` : ""}
            </span>
          </div>

          <div className="mt-1.5 flex flex-wrap gap-1">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                onClick={() => loadMode(m.value)}
                disabled={status === "loading"}
                className={`rounded border px-1.5 py-0.5 font-mono text-[9px] disabled:opacity-50 ${
                  mode === m.value
                    ? "border-accent text-accent"
                    : "border-border text-muted hover:text-foreground"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>

          {brief.grounding_rejected && (
            <p className="mt-2 text-[11px] text-warning">
              The AI provider&apos;s response could not be verified against the evidence packet and was
              replaced with a deterministic-only summary below.
            </p>
          )}

          <div className="mt-2 space-y-2">
            <TextBlock title="SITUATION" text={brief.situation_summary} />
            <TextBlock title="WHY THIS SETUP EXISTS" text={brief.setup_explanation} />
            <ListBlock title="WHAT SUPPORTS THIS VIEW" items={brief.supporting_evidence} itemClassName="text-positive" />
            <ListBlock
              title="WHAT CONTRADICTS THIS VIEW"
              items={brief.contradictory_evidence}
              itemClassName="text-negative"
            />
            <TextBlock title="CATALYST CONTEXT" text={brief.catalyst_context} />
            <TextBlock title="HISTORICAL EVIDENCE" text={brief.historical_context} />
            <ListBlock title="WHAT THE DATA DOES NOT PROVE" items={brief.uncertainty} itemClassName="text-muted" />
            <ListBlock title="INVALIDATION CONDITIONS" items={brief.invalidation_conditions} />
            <ListBlock title="MONITOR NEXT" items={brief.monitor_next} />
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border pt-2">
            <button
              type="button"
              onClick={() => setShowPacket((prev) => !prev)}
              className="rounded border border-border px-2 py-1 font-mono text-[10px] text-muted hover:text-foreground"
            >
              {showPacket ? "HIDE EVIDENCE PACKET" : "VIEW EVIDENCE PACKET"}
            </button>
            <span className="text-[9px] text-muted">RANKING GATE: {packet?.ranking_gate_status}</span>
          </div>

          {brief.evidence_refs.length > 0 && (
            <p className="mt-1.5 flex flex-wrap gap-1 text-[9px] text-muted">
              {brief.evidence_refs.map((ref) => (
                <span key={ref} className="rounded bg-border px-1 py-0.5">
                  {ref}
                </span>
              ))}
            </p>
          )}

          {showPacket && packet && (
            <pre className="mt-2 max-h-64 overflow-auto rounded border border-border bg-background p-2 text-[9px] text-muted">
              {JSON.stringify(packet, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
