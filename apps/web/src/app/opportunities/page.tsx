"use client";

import { OpportunityIntelligence } from "@/components/OpportunityIntelligence";
import { TopNav } from "@/components/TopNav";

export default function OpportunitiesPage() {
  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-4 px-6 py-6">
        <div className="flex items-center justify-between">
          <h1 className="font-mono text-lg font-semibold">Opportunity Intelligence</h1>
        </div>
        <p className="text-[11px] text-muted">
          Which stocks deserve your attention right now -- deterministic Decision-state categories over the
          monitoring universe, never a score or an implied ranking. RANKING GATE remains FAIL.
        </p>
        <OpportunityIntelligence />
      </main>
    </div>
  );
}
