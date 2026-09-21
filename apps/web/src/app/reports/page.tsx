"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { TopNav } from "@/components/TopNav";
import { listRecentBriefs } from "@/lib/api";
import { formatAiProviderLabel, formatEnumLabel, formatExchangeTimestamp } from "@/lib/format";
import type { BriefListItem } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

/**
 * Hardening pass (§19): the REPORTS nav item previously went nowhere --
 * this lists every AI ResearchBrief this process has ever persisted
 * (app.ai_analysis.repository), each permanently bound to the frozen
 * EvidencePacket it was generated from. Nothing here regenerates a report
 * from current market state.
 */
export default function ReportsPage() {
  const [items, setItems] = useState<BriefListItem[]>([]);
  const [state, setState] = useState<LoadState>("loading");

  useEffect(() => {
    listRecentBriefs()
      .then((result) => {
        setItems(result);
        setState("ready");
      })
      .catch(() => setState("error"));
  }, []);

  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-4 px-6 py-6">
        <h1 className="font-mono text-lg font-semibold">Reports</h1>

        <section className="rounded-md border border-border bg-surface">
          {state === "loading" && <p className="p-4 text-xs text-muted">Loading reports…</p>}
          {state === "error" && <p className="p-4 text-xs text-negative">Failed to load reports.</p>}
          {state === "ready" && items.length === 0 && (
            <p className="p-4 text-xs text-muted">
              No AI research reports have been generated yet. Open a setup&apos;s AI Research Analyst
              panel on the Overview page to create one.
            </p>
          )}
          {state === "ready" && items.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead>
                  <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted">
                    <th className="px-3 py-2">Symbol</th>
                    <th className="px-3 py-2">Mode</th>
                    <th className="px-3 py-2">Setup</th>
                    <th className="px-3 py-2">Generated</th>
                    <th className="px-3 py-2">Market As-Of</th>
                    <th className="px-3 py-2">Provider</th>
                    <th className="px-3 py-2">Prompt</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.brief_id} className="border-b border-border/60 last:border-0 hover:bg-surface-raised/50">
                      <td className="px-3 py-2">
                        <Link
                          href={`/reports/${item.symbol}/${item.brief_id}`}
                          className="font-semibold text-foreground hover:text-accent"
                        >
                          {item.symbol}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-muted">{formatEnumLabel(item.mode)}</td>
                      <td className="px-3 py-2 text-muted">{item.setup_id ? item.setup_id.slice(0, 12) + "…" : "symbol-level"}</td>
                      <td className="px-3 py-2 text-muted">{formatExchangeTimestamp(item.generated_at)}</td>
                      <td className="px-3 py-2 text-muted">{formatExchangeTimestamp(item.as_of)}</td>
                      <td className="px-3 py-2 text-muted">
                        {formatAiProviderLabel(item.provider)}
                        {item.model ? ` · ${item.model}` : ""}
                      </td>
                      <td className="px-3 py-2 text-muted">{item.prompt_version}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
