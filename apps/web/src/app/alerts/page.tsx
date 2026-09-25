"use client";

import { AlertCenter } from "@/components/AlertCenter";
import { TopNav } from "@/components/TopNav";

export default function AlertsPage() {
  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[900px] flex-1 space-y-4 px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="font-mono text-lg font-semibold">Alerts</h1>
        </div>
        <p className="text-[11px] text-muted">
          Deterministic changes already produced by the Decision Engine -- never a prediction, never a score.
        </p>
        <AlertCenter />
      </main>
    </div>
  );
}
