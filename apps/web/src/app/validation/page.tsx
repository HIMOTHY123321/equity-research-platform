"use client";

import { TopNav } from "@/components/TopNav";
import { ValidationLab } from "@/components/ValidationLab";

export default function ValidationPage() {
  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-4 px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="font-mono text-lg font-semibold">Prospective Validation</h1>
        </div>
        <p className="text-[11px] text-muted">
          Do the Decision Engine states have genuine prospective predictive value? Research only -- never a
          BUY/SELL recommendation, and never a substitute for the RANKING GATE.
        </p>
        <ValidationLab />
      </main>
    </div>
  );
}
