"use client";

import { formatAtr, formatSampleSizeLabel, formatSignedPercent } from "@/lib/format";
import type {
  ConclusionLabelKind,
  ContradictionResult,
  CrossSymbolStabilityReport,
  DistributionSummary,
  EvidenceMaturityKind,
  ExcursionProfile,
  FirstHitResult,
  IndependenceSection,
  OverlapReport,
  ResearchEvidenceCard,
  ResearchQueryResponse,
  SampleConcentrationReport,
  SignalDecayProfile,
  TemporalStabilityReport,
} from "@/lib/types";

function DistributionCell({ dist, digits = 2 }: { dist: DistributionSummary; digits?: number }) {
  if (dist.n === 0) return <span className="text-muted">no data</span>;
  return (
    <span>
      <span className="font-mono text-foreground">{formatSignedPercent(dist.median, digits)}</span>
      <span className="ml-1 text-[10px] text-muted">n={dist.n}</span>
    </span>
  );
}

function FlagPill({ flag }: { flag: string }) {
  const severe = ["insufficient_sample", "out_of_sample_reversal", "result_unstable"].includes(flag);
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wide ${
        severe ? "bg-negative/15 text-negative" : "bg-amber-500/15 text-amber-600 dark:text-amber-400"
      }`}
    >
      {flag.replace(/_/g, " ")}
    </span>
  );
}

function EvidenceCardBlock({ card }: { card: ResearchEvidenceCard }) {
  return (
    <div className="rounded border border-border bg-surface-raised p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          {card.setup_type.replace(/_/g, " ")} {card.direction ? `· ${card.direction}` : ""}
        </h3>
        <span className="text-[11px] text-muted">
          {card.sample_count} samples ({formatSampleSizeLabel(card.sample_size_label)})
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 text-[11px] sm:grid-cols-4">
        <div>
          <div className="text-muted">{card.horizon_bars}-bar median</div>
          <div className="font-mono text-foreground">{formatSignedPercent(card.median_directional_return)}</div>
        </div>
        <div>
          <div className="text-muted">Matched baseline</div>
          <div className="font-mono text-foreground">{formatSignedPercent(card.matched_baseline_median)}</div>
        </div>
        <div>
          <div className="text-muted">Observed excess</div>
          <div className="font-mono text-foreground">{formatSignedPercent(card.observed_excess)}</div>
        </div>
        <div>
          <div className="text-muted">Symbols positive</div>
          <div className="font-mono text-foreground">
            {card.symbols_positive}/{card.symbols_total}
          </div>
        </div>
      </div>
      <div className="mt-2 text-[11px]">
        <span className="text-muted">Bootstrap interval: </span>
        {card.bootstrap_interval.available ? (
          <span className="font-mono text-foreground">
            [{formatSignedPercent(card.bootstrap_interval.lower)}, {formatSignedPercent(card.bootstrap_interval.upper)}]
          </span>
        ) : (
          <span className="text-muted">{card.bootstrap_interval.unavailable_reason ?? "unavailable"}</span>
        )}
      </div>
      {Object.keys(card.partition_medians).length > 0 && (
        <div className="mt-2 flex gap-3 text-[11px]">
          {Object.entries(card.partition_medians).map(([partition, median]) => (
            <span key={partition}>
              <span className="text-muted">{partition}: </span>
              <span className="font-mono text-foreground">{formatSignedPercent(median)}</span>
            </span>
          ))}
        </div>
      )}
      {card.flags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {card.flags.map((flag) => (
            <FlagPill key={flag} flag={flag} />
          ))}
        </div>
      )}
    </div>
  );
}

function DecayBlock({ decay }: { decay: SignalDecayProfile }) {
  return (
    <div className="rounded border border-border bg-surface-raised p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-foreground">Signal decay</h3>
        <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-mono uppercase text-accent">
          {decay.pattern}
        </span>
      </div>
      <table className="w-full">
        <thead>
          <tr className="text-[10px] uppercase tracking-wide text-muted">
            <th className="text-left font-normal">Horizon</th>
            <th className="text-right font-normal">Median</th>
            <th className="text-right font-normal">Bootstrap CI</th>
          </tr>
        </thead>
        <tbody>
          {decay.horizons.map((h) => (
            <tr key={h.horizon_bars}>
              <td className="py-1 pr-3 font-mono text-[11px] text-muted">{h.horizon_bars} bars</td>
              <td className="py-1 pr-3 text-right">
                <DistributionCell dist={h.distribution} />
              </td>
              <td className="py-1 text-right font-mono text-[11px] text-muted">
                {h.bootstrap_interval.available
                  ? `[${formatSignedPercent(h.bootstrap_interval.lower)}, ${formatSignedPercent(h.bootstrap_interval.upper)}]`
                  : "n/a"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] text-muted">{decay.pattern_basis}</p>
    </div>
  );
}

function ExcursionBlock({ excursions, firstHit }: { excursions: ExcursionProfile; firstHit: FirstHitResult | null }) {
  return (
    <div className="rounded border border-border bg-surface-raised p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">Excursion profile</h3>
      <div className="grid grid-cols-2 gap-3 text-[11px] sm:grid-cols-3">
        <div>
          <div className="text-muted">MFE (ATR)</div>
          <div className="font-mono text-positive">{formatAtr(excursions.mfe_atr.median)}</div>
        </div>
        <div>
          <div className="text-muted">MAE (ATR)</div>
          <div className="font-mono text-negative">{formatAtr(excursions.mae_atr.median)}</div>
        </div>
        <div>
          <div className="text-muted">Bars to MFE / MAE</div>
          <div className="font-mono text-foreground">
            {excursions.bars_to_mfe.median ?? "—"} / {excursions.bars_to_mae.median ?? "—"}
          </div>
        </div>
      </div>
      {firstHit && (
        <div className="mt-3 border-t border-border pt-2 text-[11px]">
          <div className="text-muted">
            First-hit path (+{firstHit.favorable_atr_threshold} ATR vs. -{firstHit.adverse_atr_threshold} ATR),
            n={firstHit.sample_count}:
          </div>
          <div className="mt-1 flex gap-4 font-mono text-foreground">
            <span className="text-positive">favorable {firstHit.favorable_first_count}</span>
            <span className="text-negative">adverse {firstHit.adverse_first_count}</span>
            <span className="text-muted">neither {firstHit.neither_count}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function StabilityBlock({
  temporal,
  crossSymbol,
}: {
  temporal: TemporalStabilityReport;
  crossSymbol: CrossSymbolStabilityReport;
}) {
  return (
    <div className="rounded border border-border bg-surface-raised p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-foreground">Temporal stability ({temporal.granularity})</h3>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase ${
            temporal.stability === "unstable" ? "bg-negative/15 text-negative" : "bg-positive/15 text-positive"
          }`}
        >
          {temporal.stability.replace(/_/g, " ")}
        </span>
      </div>
      {temporal.buckets.length > 0 ? (
        <div className="flex flex-wrap gap-3 text-[11px]">
          {temporal.buckets.map((b) => (
            <span key={b.bucket_label}>
              <span className="text-muted">{b.bucket_label}: </span>
              <DistributionCell dist={b.distribution} />
            </span>
          ))}
        </div>
      ) : (
        <p className="text-[11px] text-muted">No buckets with data.</p>
      )}

      <h4 className="mb-1 mt-3 border-t border-border pt-2 text-[11px] font-semibold text-foreground">
        Cross-symbol ({crossSymbol.symbols_positive_median}/{crossSymbol.symbols_with_data} positive)
      </h4>
      <div className="flex flex-wrap gap-3 text-[11px]">
        {crossSymbol.per_symbol.map((s) => (
          <span key={s.symbol}>
            <span className="text-muted">{s.symbol}: </span>
            <DistributionCell dist={s.distribution} />
          </span>
        ))}
      </div>
      {crossSymbol.dispersion_of_symbol_medians !== null && (
        <p className="mt-1 text-[10px] text-muted">
          Dispersion across symbols: {crossSymbol.dispersion_of_symbol_medians.toFixed(3)}
        </p>
      )}
    </div>
  );
}

function ConcentrationAndOverlapBlock({
  concentration,
  overlap,
}: {
  concentration: SampleConcentrationReport;
  overlap: OverlapReport;
}) {
  if (concentration.warnings.length === 0 && !overlap.warning) return null;
  return (
    <div className="rounded border border-amber-500/40 bg-amber-500/5 p-4">
      <h3 className="mb-2 text-sm font-semibold text-amber-600 dark:text-amber-400">Evidence warnings</h3>
      <ul className="space-y-1 text-[11px] text-foreground">
        {concentration.warnings.map((w) => (
          <li key={w.dimension}>{w.warning}</li>
        ))}
        {overlap.warning && <li>{overlap.warning}</li>}
      </ul>
    </div>
  );
}

const MATURITY_STYLE: Record<EvidenceMaturityKind, string> = {
  insufficient: "bg-negative/15 text-negative",
  preliminary: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  mixed: "bg-negative/15 text-negative",
  replicated: "bg-positive/15 text-positive",
};

const CONCLUSION_LABEL_STYLE: Record<ConclusionLabelKind, string> = {
  survives: "bg-positive/15 text-positive",
  weakens: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  disappears: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  reverses: "bg-negative/15 text-negative",
  insufficient_independent_sample: "bg-border text-muted",
};

function IndependenceBlock({ independence }: { independence: IndependenceSection }) {
  const { sample_composition, walk_forward, evidence_maturity, evidence_maturity_basis, conclusion_stability } =
    independence;
  return (
    <div className="rounded border border-border bg-surface-raised p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-foreground">Independence &amp; robustness</h3>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase ${MATURITY_STYLE[evidence_maturity]}`}
        >
          {evidence_maturity}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 text-[11px] sm:grid-cols-4">
        <div>
          <div className="text-muted">Raw observations</div>
          <div className="font-mono text-foreground">{sample_composition.raw_count}</div>
        </div>
        <div>
          <div className="text-muted">Independent episodes</div>
          <div className="font-mono text-foreground">{sample_composition.episode_count}</div>
        </div>
        {Object.entries(sample_composition.purged_counts_by_horizon).map(([horizon, count]) => (
          <div key={horizon}>
            <div className="text-muted">Purged ({horizon}-bar)</div>
            <div className="font-mono text-foreground">{count}</div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10px] text-muted">{evidence_maturity_basis}</p>

      <h4 className="mb-1 mt-3 flex items-baseline gap-2 border-t border-border pt-2 text-[11px] font-semibold text-foreground">
        Walk-forward stability
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase ${
            walk_forward.stability === "unstable"
              ? "bg-negative/15 text-negative"
              : walk_forward.stability === "stable"
                ? "bg-positive/15 text-positive"
                : "bg-border text-muted"
          }`}
        >
          {walk_forward.stability.replace(/_/g, " ")}
        </span>
      </h4>
      {walk_forward.windows.length > 0 ? (
        <div className="flex flex-wrap gap-3 text-[11px]">
          {walk_forward.windows.map((w) => (
            <span key={w.window_index}>
              <span className="text-muted">fold {w.window_index}: </span>
              <DistributionCell dist={w.test_distribution} />
            </span>
          ))}
        </div>
      ) : (
        <p className="text-[11px] text-muted">Not enough entries to build walk-forward folds.</p>
      )}
      {walk_forward.windows.length > 0 && (
        <p className="mt-1 text-[10px] text-muted">
          {walk_forward.positive_median_window_count} positive / {walk_forward.negative_median_window_count}{" "}
          negative folds
        </p>
      )}

      {conclusion_stability && (
        <div className="mt-3 border-t border-border pt-2">
          <h4 className="mb-1 flex items-baseline gap-2 text-[11px] font-semibold text-foreground">
            <span>Conclusion stability: {conclusion_stability.finding_label}</span>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase ${
                CONCLUSION_LABEL_STYLE[conclusion_stability.label]
              }`}
            >
              {conclusion_stability.label.replace(/_/g, " ")}
            </span>
          </h4>
          <table className="w-full">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-muted">
                <th className="text-left font-normal">Level</th>
                <th className="text-right font-normal">{conclusion_stability.raw.group_a_label}</th>
                <th className="text-right font-normal">{conclusion_stability.raw.group_b_label}</th>
                <th className="text-right font-normal">Difference</th>
              </tr>
            </thead>
            <tbody>
              {(["raw", "episode", "purged"] as const).map((level) => {
                const c = conclusion_stability[level];
                return (
                  <tr key={level}>
                    <td className="py-1 pr-3 font-mono text-[11px] capitalize text-muted">{level}</td>
                    <td className="py-1 pr-3 text-right">
                      <DistributionCell dist={c.group_a_distribution} />
                    </td>
                    <td className="py-1 pr-3 text-right">
                      <DistributionCell dist={c.group_b_distribution} />
                    </td>
                    <td className="py-1 text-right font-mono text-[11px] text-foreground">
                      {formatSignedPercent(c.median_difference)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-1 text-[10px] text-muted">{conclusion_stability.label_basis}</p>
        </div>
      )}
    </div>
  );
}

function ContradictionsBlock({ contradictions }: { contradictions: ContradictionResult[] }) {
  return (
    <div className="rounded border border-border bg-surface-raised p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">Research contradictions</h3>
      <ul className="space-y-2">
        {contradictions.map((c) => (
          <li key={c.assumption_code} className="text-[11px]">
            <div className="flex items-baseline justify-between">
              <span className="text-foreground">{c.description}</span>
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase ${
                  c.status === "assumption_not_supported_in_this_sample"
                    ? "bg-negative/15 text-negative"
                    : c.status === "assumption_supported"
                      ? "bg-positive/15 text-positive"
                      : "bg-border text-muted"
                }`}
              >
                {c.status.replace(/_/g, " ")}
              </span>
            </div>
            <div className="mt-0.5 text-muted">
              {c.group_a_label}: <span className="font-mono text-foreground">{formatSignedPercent(c.comparison.group_a_distribution.median)}</span>
              {" · "}
              {c.group_b_label}: <span className="font-mono text-foreground">{formatSignedPercent(c.comparison.group_b_distribution.median)}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ResearchResultsPanel({ result }: { result: ResearchQueryResponse }) {
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted">{result.sample_count} total pooled samples</p>
      <EvidenceCardBlock card={result.evidence_card} />
      <ConcentrationAndOverlapBlock concentration={result.concentration} overlap={result.overlap} />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <DecayBlock decay={result.signal_decay} />
        <ExcursionBlock excursions={result.excursions} firstHit={result.first_hit} />
      </div>
      <StabilityBlock temporal={result.temporal_stability} crossSymbol={result.cross_symbol_stability} />
      <IndependenceBlock independence={result.independence} />
      <ContradictionsBlock contradictions={result.contradictions} />
    </div>
  );
}
