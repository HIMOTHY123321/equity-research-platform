"use client";

import { formatAtr, formatSampleSizeLabel, formatSetupType, formatSignedPercent } from "@/lib/format";
import type { GroupOutcomeStats, SetupTypeSummary } from "@/lib/types";

function HorizonRow({ label, qualified, rejected }: { label: string; qualified: GroupOutcomeStats; rejected: GroupOutcomeStats }) {
  const q = qualified.directional_return_by_horizon.find((h) => String(h.horizon_bars) === label);
  const r = rejected.directional_return_by_horizon.find((h) => String(h.horizon_bars) === label);
  return (
    <tr>
      <td className="py-1 pr-3 font-mono text-[11px] text-muted">{label} bar{label === "1" ? "" : "s"}</td>
      <td className="py-1 pr-3 text-right font-mono text-xs text-positive">
        {q ? formatSignedPercent(q.median) : "—"}
        <span className="ml-1 text-[10px] text-muted">n={q?.n ?? 0}</span>
      </td>
      <td className="py-1 text-right font-mono text-xs text-negative">
        {r ? formatSignedPercent(r.median) : "—"}
        <span className="ml-1 text-[10px] text-muted">n={r?.n ?? 0}</span>
      </td>
    </tr>
  );
}

export function SetupTypeResearchCard({ summary }: { summary: SetupTypeSummary }) {
  const lift5 = summary.qualification_lift.find((l) => l.horizon_bars === 5);

  return (
    <div className="rounded border border-border bg-surface-raised p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-foreground">{formatSetupType(summary.setup_type)}</h3>
        <div className="flex gap-3 text-[11px] text-muted">
          <span>
            Qualified: <span className="font-mono text-foreground">{summary.qualified.sample_count}</span>{" "}
            <span className="text-[10px]">({formatSampleSizeLabel(summary.qualified.sample_size_label)})</span>
          </span>
          <span>
            Rejected: <span className="font-mono text-foreground">{summary.rejected.sample_count}</span>{" "}
            <span className="text-[10px]">({formatSampleSizeLabel(summary.rejected.sample_size_label)})</span>
          </span>
        </div>
      </div>

      <table className="w-full">
        <thead>
          <tr className="text-[10px] uppercase tracking-wide text-muted">
            <th className="text-left font-normal">Horizon</th>
            <th className="text-right font-normal">Qualified median</th>
            <th className="text-right font-normal">Rejected median</th>
          </tr>
        </thead>
        <tbody>
          {["1", "3", "5", "10", "20"].map((h) => (
            <HorizonRow key={h} label={h} qualified={summary.qualified} rejected={summary.rejected} />
          ))}
        </tbody>
      </table>

      {lift5 && (
        <p className="mt-2 text-[11px] text-muted">
          Observed 5-bar difference (qualified vs. rejected):{" "}
          <span className={`font-mono ${(lift5.observed_difference ?? 0) >= 0 ? "text-positive" : "text-negative"}`}>
            {formatSignedPercent(lift5.observed_difference)}
          </span>{" "}
          <span className="text-[10px]">(descriptive, not a causal claim)</span>
        </p>
      )}

      <div className="mt-2 grid grid-cols-2 gap-3 text-[11px]">
        <div>
          <span className="text-muted">MFE median: </span>
          <span className="font-mono text-positive">{formatAtr(summary.qualified.mfe_atr?.median ?? null)}</span>
        </div>
        <div>
          <span className="text-muted">MAE median: </span>
          <span className="font-mono text-negative">{formatAtr(summary.qualified.mae_atr?.median ?? null)}</span>
        </div>
      </div>

      {summary.baseline && (
        <p className="mt-2 text-[11px] text-muted">
          Baseline ({summary.baseline.regime_label} regime, 5-bar):{" "}
          {(() => {
            const unconditional = summary.baseline!.unconditional.directional_return_by_horizon.find(
              (h) => h.horizon_bars === 5,
            );
            const regime = summary.baseline!.regime_matched?.directional_return_by_horizon.find(
              (h) => h.horizon_bars === 5,
            );
            return (
              <>
                unconditional <span className="font-mono text-foreground">{formatSignedPercent(unconditional?.median ?? null)}</span>
                {regime && (
                  <>
                    {" "}· regime-matched <span className="font-mono text-foreground">{formatSignedPercent(regime.median)}</span>
                  </>
                )}
              </>
            );
          })()}
        </p>
      )}

      {summary.rejection_value.length > 0 && (
        <div className="mt-3 border-t border-border pt-2">
          <h4 className="mb-1 text-[10px] font-semibold tracking-wide text-muted">WHY NOT? PERFORMANCE</h4>
          <ul className="space-y-1">
            {summary.rejection_value.map((rv) => (
              <li key={rv.rejection_code} className="flex items-center justify-between text-[11px]">
                <span className="text-muted">
                  {rv.rejection_code.replace(/_/g, " ")} · n={rv.sample_count} (
                  {formatSampleSizeLabel(rv.sample_size_label)})
                </span>
                <span className="font-mono text-foreground">
                  {formatSignedPercent(rv.median_5bar_directional_return)} vs. qualified{" "}
                  {formatSignedPercent(rv.comparable_qualified_median_5bar_directional_return)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
