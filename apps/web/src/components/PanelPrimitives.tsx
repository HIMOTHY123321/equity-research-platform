import type { ReactNode } from "react";

export function Row({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-[11px] text-muted">{label}</span>
      <span className={`font-mono text-xs ${valueClassName ?? "text-foreground"}`}>{value}</span>
    </div>
  );
}

export function Block({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded border border-border bg-surface-raised p-3">
      <h3 className="mb-1.5 text-[11px] font-semibold tracking-wide text-muted">{title}</h3>
      <div>{children}</div>
    </div>
  );
}
