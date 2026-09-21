"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { EvidenceAuditTrail } from "@/components/EvidenceAuditTrail";
import { TopNav } from "@/components/TopNav";
import { ApiError, getResearchBrief, getSavedEvidencePacket } from "@/lib/api";
import { formatEnumLabel, formatExchangeTimestamp } from "@/lib/format";
import type { EvidencePacket, ResearchBrief } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

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
 * Hardening pass (§19): opening a saved report shows exactly the frozen
 * ResearchBrief + the EvidencePacket it was bound to at generation time --
 * fetched by id, never rebuilt from current market state (see
 * app.api.routes.analysis.get_saved_evidence_packet's docstring).
 */
export default function ReportDetailPage() {
  const params = useParams<{ symbol: string; briefId: string }>();
  const [brief, setBrief] = useState<ResearchBrief | null>(null);
  const [packet, setPacket] = useState<EvidencePacket | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setState("loading");
      try {
        const briefResult = await getResearchBrief(params.symbol, params.briefId);
        const packetResult = await getSavedEvidencePacket(params.symbol, briefResult.evidence_packet_id);
        if (cancelled) return;
        setBrief(briefResult);
        setPacket(packetResult);
        setState("ready");
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load report");
        setState("error");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [params.symbol, params.briefId]);

  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[900px] flex-1 space-y-4 px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="font-mono text-lg font-semibold">
            {params.symbol} Report
          </h1>
          <Link href="/reports" className="text-xs text-muted hover:text-foreground">
            ← All reports
          </Link>
        </div>

        {state === "loading" && <p className="text-xs text-muted">Loading report…</p>}
        {state === "error" && <p className="text-xs text-negative">{error}</p>}

        {state === "ready" && brief && (
          <div className="rounded-md border border-border bg-surface p-3">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
              <h2 className="text-xs font-semibold tracking-wide text-foreground">
                {formatEnumLabel(brief.mode)} · {formatExchangeTimestamp(brief.generated_at)}
              </h2>
              <span className="rounded bg-border px-1.5 py-0.5 text-[9px] uppercase text-muted">
                {brief.provider}
                {brief.model ? ` · ${brief.model}` : ""} · {brief.prompt_version}
              </span>
            </div>

            {brief.grounding_rejected && (
              <p className="mt-2 text-[11px] text-warning">
                The AI provider&apos;s response could not be verified against the evidence packet at the
                time this report was generated and was replaced with a deterministic-only summary below.
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

            {packet && (
              <div className="mt-2 border-t border-border pt-2">
                <h5 className="mb-1 text-[10px] font-semibold tracking-wide text-muted">
                  EVIDENCE PROVENANCE (RANKING GATE: {packet.ranking_gate_status})
                </h5>
                <EvidenceAuditTrail packet={packet} brief={brief} />
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
