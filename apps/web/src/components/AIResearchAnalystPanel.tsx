"use client";

import { useEffect, useState } from "react";

import { EvidenceAuditTrail } from "@/components/EvidenceAuditTrail";
import { ApiError, getEvidencePacket, postResearchBrief } from "@/lib/api";
import { formatAiProviderLabel } from "@/lib/format";
import type { AnalysisMode, EvidencePacket, ResearchBrief, SetupCandidate } from "@/lib/types";

type Status = "idle" | "loading" | "loaded" | "failed";

// Honest, conservative "evidence may have moved on" threshold -- see the
// useEffect below for the full rationale.
const STALE_SESSION_MS = 5 * 60 * 1000;

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
 *
 * Hardening pass (§V): opening this panel freezes exactly ONE EvidencePacket
 * -- its `as_of` is pinned in `frozenAsOf` and passed explicitly on every
 * subsequent mode switch. build_evidence_packet is deterministic for a
 * given (symbol, timeframe, setup_id, as_of), so reusing the same as_of
 * reproduces the exact same packet_id/content; switching QUICK/FULL/WHY_
 * THIS_SETUP/WHY_NOT/CATALYST/ANALOGS only changes synthesis/presentation,
 * never the underlying evidence. Background market movement never mutates
 * an open session -- "NEW EVIDENCE AVAILABLE" only ever offers a fresh
 * snapshot via an explicit, separate packet (§V "new packet, old one
 * preserved").
 */
export function AIResearchAnalystPanel({ candidate }: { candidate: SetupCandidate }) {
  const [status, setStatus] = useState<Status>("idle");
  const [mode, setMode] = useState<AnalysisMode>("full");
  const [brief, setBrief] = useState<ResearchBrief | null>(null);
  const [packet, setPacket] = useState<EvidencePacket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showPacket, setShowPacket] = useState(false);
  const [frozenAsOf, setFrozenAsOf] = useState<string | null>(null);
  const [openedAt, setOpenedAt] = useState<number | null>(null);
  const [newEvidenceAvailable, setNewEvidenceAvailable] = useState(false);

  async function loadMode(nextMode: AnalysisMode, asOf: string) {
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
          asOf,
        }),
        getEvidencePacket({
          symbol: candidate.symbol,
          timeframe: candidate.timeframe,
          setupId: candidate.id,
          asOf,
        }),
      ]);
      setBrief(briefResult);
      setPacket(packetResult);
      setStatus("loaded");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "AI Research Analyst is unavailable");
      setStatus("failed");
    }
  }

  async function freezeAndLoad(nextMode: AnalysisMode) {
    // The one and only place a fresh "now" is chosen -- every subsequent
    // mode switch within this session reuses it (see loadMode above).
    const asOf = new Date().toISOString();
    setFrozenAsOf(asOf);
    setOpenedAt(Date.now());
    setNewEvidenceAvailable(false);
    await loadMode(nextMode, asOf);
  }

  async function toggle() {
    if (status === "loading") return;
    if (brief) {
      setBrief(null);
      setPacket(null);
      setFrozenAsOf(null);
      setOpenedAt(null);
      setNewEvidenceAvailable(false);
      setStatus("idle");
      return;
    }
    await freezeAndLoad(mode);
  }

  function switchMode(nextMode: AnalysisMode) {
    if (!frozenAsOf) return;
    loadMode(nextMode, frozenAsOf);
  }

  async function newAnalysisSnapshot() {
    // A deliberate, explicit new packet -- the old one (and any saved
    // report generated from it) is never touched, only superseded in this
    // panel's own view.
    await freezeAndLoad(mode);
  }

  // Honest, conservative "evidence may have moved on" signal: once this
  // session's frozen packet is more than one bar-length old (approximated
  // as 5 minutes -- the finest interval this product currently supports),
  // a genuinely newer completed bar/catalyst could plausibly exist. This
  // never claims to know FOR CERTAIN that new evidence exists (that would
  // require re-querying), only that enough time has passed that checking
  // is worthwhile. Checked on an interval, never inline in render.
  useEffect(() => {
    if (!openedAt) return;
    const check = () => {
      if (Date.now() - openedAt > STALE_SESSION_MS) setNewEvidenceAvailable(true);
    };
    check();
    const interval = setInterval(check, 15_000);
    return () => clearInterval(interval);
  }, [openedAt]);

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
              {formatAiProviderLabel(brief.provider)}
              {brief.model ? ` · ${brief.model}` : ""}
            </span>
          </div>

          <div className="mt-1.5 flex flex-wrap gap-1">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                onClick={() => switchMode(m.value)}
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

          {newEvidenceAvailable && (
            <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 rounded border border-accent/40 bg-accent/10 px-2 py-1">
              <span className="text-[10px] text-accent">
                NEW EVIDENCE AVAILABLE -- this analysis is frozen as of{" "}
                {frozenAsOf ? new Date(frozenAsOf).toLocaleTimeString() : ""}.
              </span>
              <button
                type="button"
                onClick={newAnalysisSnapshot}
                disabled={status === "loading"}
                className="rounded border border-accent px-1.5 py-0.5 font-mono text-[9px] text-accent disabled:opacity-50"
              >
                NEW ANALYSIS SNAPSHOT
              </button>
            </div>
          )}

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

          {showPacket && packet && <EvidenceAuditTrail packet={packet} brief={brief} />}
        </div>
      )}
    </div>
  );
}
