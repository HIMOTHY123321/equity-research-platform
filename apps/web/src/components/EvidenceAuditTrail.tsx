"use client";

import { useState } from "react";

import {
  formatCatalystContextLabel,
  formatClockTime,
  formatEvidenceMaturity,
  formatPrice,
  formatSetupType,
} from "@/lib/format";
import type { EvidencePacket, ResearchBrief } from "@/lib/types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-border pt-2">
      <h6 className="text-[9px] font-semibold tracking-wide text-muted">{title}</h6>
      <div className="mt-1 space-y-0.5 text-[11px] text-foreground">{children}</div>
    </div>
  );
}

function RefChips({ refs }: { refs: string[] }) {
  if (refs.length === 0) return <p className="text-muted">No evidence references.</p>;
  return (
    <p className="flex flex-wrap gap-1">
      {refs.map((ref) => (
        <span key={ref} className="rounded bg-border px-1 py-0.5 font-mono text-[9px] text-muted">
          {ref}
        </span>
      ))}
    </p>
  );
}

/**
 * Phase 11.1 (#K): "VIEW EVIDENCE PACKET" as a real audit surface -- not raw
 * JSON as the primary presentation. Every section here answers "why did
 * the AI say this?" by pointing back at the specific deterministic
 * evidence it was grounded against. Raw JSON remains available as an
 * explicit secondary/developer view.
 */
export function EvidenceAuditTrail({ packet, brief }: { packet: EvidencePacket; brief: ResearchBrief }) {
  const [showRawJson, setShowRawJson] = useState(false);

  return (
    <div className="mt-2 space-y-2 rounded border border-border bg-background p-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h5 className="text-[10px] font-semibold tracking-wide text-muted">EVIDENCE AUDIT TRAIL</h5>
        <span
          className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${
            packet.mode === "live" ? "bg-accent/15 text-accent" : "bg-warning/15 text-warning"
          }`}
        >
          {packet.mode === "live" ? "LIVE" : "HISTORICAL SNAPSHOT"}
        </span>
      </div>

      <Section title="PACKET ID / AS OF / PIPELINE VERSION">
        <p className="font-mono text-[10px]">{packet.packet_id}</p>
        <p>
          As of {formatClockTime(packet.as_of)} on {new Date(packet.as_of).toLocaleDateString()} ·
          Pipeline v{packet.pipeline_version} · Schema v{packet.schema_version}
        </p>
      </Section>

      <Section title="MARKET DATA / NEWS / RESEARCH CUTOFFS">
        <p>Market data: {packet.market_data_cutoff ? formatClockTime(packet.market_data_cutoff) : "unavailable"}</p>
        <p>News: {packet.news_cutoff ? formatClockTime(packet.news_cutoff) : "not included"}</p>
        <p>
          Research snapshot:{" "}
          {packet.research_snapshot_cutoff ? formatClockTime(packet.research_snapshot_cutoff) : "no runs available"}
        </p>
      </Section>

      {packet.setup && (
        <Section title="SETUP EVIDENCE">
          <p>
            {formatSetupType(packet.setup.candidate.setup_type)} — {packet.setup.qualified ? "qualified" : "not qualified"}
          </p>
          {packet.setup.qualification_reasons.map((r) => (
            <p key={r} className="text-positive">
              ✓ {r}
            </p>
          ))}
          {packet.setup.rejection_reasons.map((r) => (
            <p key={r} className="text-negative">
              ✕ {r}
            </p>
          ))}
        </Section>
      )}

      <Section title="STRUCTURE EVIDENCE">
        <p>Trend: {packet.structure.trend.trend}</p>
        <p>Breaks of structure: {packet.structure.breaks_of_structure.length}</p>
        <p>Changes of character: {packet.structure.changes_of_character.length}</p>
      </Section>

      <Section title="LEVEL EVIDENCE">
        <p>
          Nearest support:{" "}
          {packet.support_resistance.nearest_support
            ? formatPrice(packet.support_resistance.nearest_support.representative_price)
            : "none"}
        </p>
        <p>
          Nearest resistance:{" "}
          {packet.support_resistance.nearest_resistance
            ? formatPrice(packet.support_resistance.nearest_resistance.representative_price)
            : "none"}
        </p>
      </Section>

      <Section title="RESEARCH EVIDENCE">
        {packet.historical_research ? (
          <>
            <p>Raw sample count: {packet.historical_research.sample_count}</p>
            <p>Episode count: {packet.historical_research.independence.sample_composition.episode_count}</p>
            <p>Evidence maturity: {formatEvidenceMaturity(packet.historical_research.independence.evidence_maturity)}</p>
          </>
        ) : (
          <p className="text-muted">No historical research available for this as_of.</p>
        )}
      </Section>

      <Section title="CATALYST EVIDENCE">
        {packet.catalyst_context ? (
          <p>{formatCatalystContextLabel(packet.catalyst_context.label)} — {packet.catalyst_context.label_basis}</p>
        ) : packet.nearest_catalyst_event ? (
          <p>{packet.nearest_catalyst_event.title}</p>
        ) : (
          <p className="text-muted">No catalyst evidence available.</p>
        )}
      </Section>

      <Section title="ANALOG EVIDENCE">
        {packet.historical_analogs && packet.historical_analogs.analogs.length > 0 ? (
          <p>
            {packet.historical_analogs.analogs.length} analog(s) ·{" "}
            {packet.historical_analogs.diversity.distinct_episode_count} distinct episode(s)
          </p>
        ) : (
          <p className="text-muted">No historical analogs available.</p>
        )}
      </Section>

      <Section title="AI BRIEF → EVIDENCE REFS">
        <RefChips refs={brief.evidence_refs} />
      </Section>

      <div className="border-t border-border pt-2">
        <button
          type="button"
          onClick={() => setShowRawJson((prev) => !prev)}
          className="rounded border border-border px-2 py-1 font-mono text-[10px] text-muted hover:text-foreground"
        >
          {showRawJson ? "HIDE RAW JSON" : "VIEW RAW JSON (DEVELOPER)"}
        </button>
        {showRawJson && (
          <pre className="mt-2 max-h-64 overflow-auto rounded border border-border bg-surface-raised p-2 text-[9px] text-muted">
            {JSON.stringify(packet, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
