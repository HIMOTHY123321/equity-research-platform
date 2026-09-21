"use client";

import { useState } from "react";

import { AnalogSearchButton } from "@/components/AnalogSearchButton";
import { ApiError, getCatalystEvent, getSetupCatalystContext } from "@/lib/api";
import {
  catalystContextLabelColorClass,
  formatCatalystCategory,
  formatCatalystContextLabel,
  formatHoursAgo,
  formatRatio,
  formatSignedPercent,
  formatSourceCount,
} from "@/lib/format";
import type { CatalystEventDetail, SetupCandidate, SetupCatalystContext } from "@/lib/types";

type Status = "idle" | "loading" | "loaded" | "failed";

/**
 * Setup Intelligence integration (#K.3): descriptive catalyst context only
 * -- no BUY/SELL/STRONG BUY/confidence score anywhere here, per the product
 * boundary this phase does not cross (Phase 9's RANKING GATE stands).
 * Click-to-load, same "no new always-on network call" discipline
 * AnalogSearchButton already established.
 */
export function CatalystContextCard({ candidate }: { candidate: SetupCandidate }) {
  const [status, setStatus] = useState<Status>("idle");
  const [context, setContext] = useState<SetupCatalystContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [eventDetail, setEventDetail] = useState<CatalystEventDetail | null>(null);

  async function load() {
    if (status === "loading") return;
    if (context) {
      setContext(null);
      setEventDetail(null);
      setStatus("idle");
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      setContext(await getSetupCatalystContext(candidate));
      setStatus("loaded");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load catalyst context");
      setStatus("failed");
    }
  }

  async function toggleCatalyst() {
    if (!context?.nearest_catalyst) return;
    if (eventDetail) {
      setEventDetail(null);
      return;
    }
    try {
      setEventDetail(await getCatalystEvent(context.nearest_catalyst.event_id));
    } catch {
      // best-effort -- source article links are a convenience, not required
    }
  }

  const nearest = context?.nearest_catalyst;
  const reaction = context?.nearest_reaction;
  const initialReaction = reaction?.price_horizons.find((h) => h.horizon_bars === 1 && h.available) ?? null;

  return (
    <div className="mt-2 border-t border-border pt-2">
      <button
        type="button"
        onClick={load}
        disabled={status === "loading"}
        className="rounded border border-accent px-2.5 py-1 font-mono text-[10px] font-semibold text-accent disabled:opacity-50"
      >
        {status === "loading" ? "LOADING…" : context ? "HIDE CATALYST CONTEXT" : "VIEW CATALYST CONTEXT"}
      </button>

      {status === "failed" && error && <p className="mt-1 text-[11px] text-negative">{error}</p>}

      {context && (
        <div className="mt-2 rounded border border-border bg-surface-raised p-2.5">
          <h5 className="text-[10px] font-semibold tracking-wide text-muted">CATALYST CONTEXT</h5>
          <p className={`mt-1 text-xs font-semibold ${catalystContextLabelColorClass(context.label)}`}>
            {formatCatalystContextLabel(context.label)}
          </p>

          {!nearest && <p className="mt-1 text-[11px] text-muted">{context.label_basis}</p>}

          {nearest && (
            <div className="mt-1.5 space-y-0.5 text-[11px] text-foreground">
              <p>
                <span
                  className={`mr-1 rounded px-1 py-0.5 font-mono text-[9px] uppercase tracking-wide ${
                    nearest.hours_after_setup !== null
                      ? "bg-muted/15 text-muted"
                      : "bg-accent/15 text-accent"
                  }`}
                >
                  {nearest.hours_after_setup !== null ? "Post-setup" : "Pre-setup"}
                </span>
                {formatCatalystCategory(nearest.category)}
                {nearest.hours_before_setup !== null &&
                  ` — ${formatHoursAgo(nearest.hours_before_setup)} before setup`}
                {nearest.hours_after_setup !== null &&
                  ` — ${formatHoursAgo(nearest.hours_after_setup)} after setup`}
              </p>
              {/* (§M) A catalyst that occurred after setup detection cannot
                  have caused the setup -- said explicitly, never left for
                  the user to infer from a bare time delta. */}
              {nearest.hours_after_setup !== null && (
                <p className="text-muted">Not part of original setup evidence.</p>
              )}
              <p className="text-muted">{formatSourceCount(nearest.source_count)}</p>
              {initialReaction && (
                <p>Initial reaction: {formatSignedPercent(initialReaction.directional_return_percent)}</p>
              )}
              {reaction?.rvol_at_event !== null && reaction?.rvol_at_event !== undefined && (
                <p>RVOL {formatRatio(reaction.rvol_at_event)}</p>
              )}
              {reaction?.structure_state_at_event && <p>Structure: {reaction.structure_state_at_event}</p>}
              {reaction?.bos_after_event && <p>Break of structure after this catalyst</p>}
            </div>
          )}

          {nearest && (
            <div className="mt-2 flex flex-wrap items-start gap-2">
              <button
                type="button"
                onClick={toggleCatalyst}
                className="rounded border border-border px-2 py-1 font-mono text-[10px] text-muted hover:text-foreground"
              >
                {eventDetail ? "HIDE CATALYST" : "VIEW CATALYST"}
              </button>
            </div>
          )}

          {eventDetail && (
            <ul className="mt-2 space-y-1 border-t border-border pt-2">
              {eventDetail.articles.map((article) => (
                <li key={article.article_id} className="text-[11px]">
                  <span className="text-muted">{article.source ?? article.provider}</span>
                  {" — "}
                  {article.url ? (
                    <a href={article.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                      {article.headline}
                    </a>
                  ) : (
                    <span className="text-foreground">{article.headline}</span>
                  )}
                </li>
              ))}
            </ul>
          )}

          {nearest && (
            <AnalogSearchButton
              candidate={candidate}
              includeCatalystContext
              label="HISTORICAL CATALYST ANALOGS"
            />
          )}
        </div>
      )}
    </div>
  );
}
