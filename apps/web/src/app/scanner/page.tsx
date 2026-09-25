"use client";

import { DecisionScanner } from "@/components/DecisionScanner";
import { TopNav } from "@/components/TopNav";

export default function ScannerPage() {
  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-4 px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="font-mono text-lg font-semibold">Decision Scanner</h1>
        </div>
        <p className="text-[11px] text-muted">
          Deterministic state across the whole monitoring universe -- not a ranking. RANKING GATE remains FAIL.
        </p>
        <DecisionScanner />
      </main>
    </div>
  );
}
