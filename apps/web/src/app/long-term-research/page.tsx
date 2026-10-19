"use client";

import { LongTermResearchPanel } from "@/components/LongTermResearchPanel";
import { TopNav } from "@/components/TopNav";

export default function LongTermResearchPage() {
  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-4 px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="font-mono text-lg font-semibold">Long-Term Research</h1>
        </div>
        <p className="text-[11px] text-muted">
          A once-a-day, deterministic long-term investing research scan of your watchlist -- separate from the
          short/medium-term Decision Engine above. Never a BUY/SELL recommendation; every research state is
          backed by transparent, listed evidence.
        </p>
        <LongTermResearchPanel />
      </main>
    </div>
  );
}
