"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { TopNav } from "@/components/TopNav";
import {
  GLOSSARY_CATEGORIES,
  GLOSSARY_TERMS,
  type GlossaryCategoryId,
  type GlossaryTermEntry,
  searchGlossary,
  termsInCategory,
} from "@/lib/glossary";

export default function GlossaryPage() {
  return (
    <Suspense fallback={null}>
      <GlossaryPageInner />
    </Suspense>
  );
}

function GlossaryPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const deepLinkedTermId = searchParams.get("term");
  const deepLinkedTerm = deepLinkedTermId
    ? GLOSSARY_TERMS.find((t) => t.id === deepLinkedTermId)
    : undefined;

  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<GlossaryCategoryId>>(
    () => new Set(deepLinkedTerm ? [deepLinkedTerm.category] : []),
  );

  const termRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (deepLinkedTerm) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setExpanded((prev) => new Set(prev).add(deepLinkedTerm.category));
      // A fresh navigation to a specific term -- scroll it into view once
      // the accordion has had a chance to render it open.
      const el = termRefs.current[deepLinkedTerm.id];
      el?.scrollIntoView({ block: "center" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkedTermId]);

  const searchResults = useMemo(() => searchGlossary(query), [query]);
  const isSearching = query.trim().length > 0;

  function toggleCategory(id: GlossaryCategoryId) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function clearDeepLink() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("term");
    router.replace(params.toString() ? `/glossary?${params}` : "/glossary", { scroll: false });
  }

  return (
    <div className="flex min-h-full flex-col">
      <TopNav />
      <main className="mx-auto w-full max-w-[1000px] flex-1 space-y-4 px-6 py-6">
        <div>
          <h1 className="font-mono text-lg font-semibold">Glossary</h1>
          <p className="mt-1 text-xs text-muted">
            Plain-English definitions for every term used across AI Market Desk -- trading basics,
            chart/market structure, historical research, forecasting, and the evidence/validation
            system. Descriptions here explain what a term observes, not what it predicts.
          </p>
        </div>

        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="SEARCH TERMS…"
          aria-label="Search glossary terms"
          className="w-full rounded border border-border bg-surface px-3 py-2 font-mono text-xs text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
        />

        {isSearching ? (
          <section aria-label="Search results" className="space-y-2">
            <h2 className="text-[10px] uppercase tracking-wide text-muted">
              {searchResults.length} result{searchResults.length === 1 ? "" : "s"}
            </h2>
            {searchResults.length === 0 && (
              <p className="text-xs text-muted">No glossary terms match &quot;{query}&quot;.</p>
            )}
            <div className="space-y-2">
              {searchResults.map((entry) => (
                <GlossaryEntryCard key={entry.id} entry={entry} />
              ))}
            </div>
          </section>
        ) : (
          <div className="space-y-2">
            {GLOSSARY_CATEGORIES.map((category) => {
              const terms = termsInCategory(category.id);
              const isOpen = expanded.has(category.id);
              return (
                <section key={category.id} className="rounded-md border border-border bg-surface">
                  <button
                    type="button"
                    onClick={() => toggleCategory(category.id)}
                    aria-expanded={isOpen}
                    aria-controls={`glossary-category-${category.id}`}
                    className="flex w-full items-center justify-between px-3 py-2.5 text-left font-mono text-xs font-semibold text-foreground"
                  >
                    <span>
                      {category.label} <span className="text-muted">({terms.length})</span>
                    </span>
                    <span className="text-muted">{isOpen ? "−" : "+"}</span>
                  </button>
                  {isOpen && (
                    <div id={`glossary-category-${category.id}`} className="space-y-2 border-t border-border p-3">
                      {terms.map((entry) => (
                        <div
                          key={entry.id}
                          ref={(el) => {
                            termRefs.current[entry.id] = el;
                          }}
                        >
                          <GlossaryEntryCard
                            entry={entry}
                            highlighted={entry.id === deepLinkedTermId}
                            onDismissHighlight={entry.id === deepLinkedTermId ? clearDeepLink : undefined}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}

function GlossaryEntryCard({
  entry,
  highlighted = false,
  onDismissHighlight,
}: {
  entry: GlossaryTermEntry;
  highlighted?: boolean;
  onDismissHighlight?: () => void;
}) {
  return (
    <article
      tabIndex={-1}
      className={`rounded border p-2.5 font-mono text-[11px] leading-relaxed ${
        highlighted ? "border-accent bg-accent/5" : "border-border"
      }`}
    >
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="font-semibold text-foreground">
          {entry.term}
          {entry.abbreviation && <span className="text-muted"> ({entry.abbreviation})</span>}
        </h3>
        {highlighted && onDismissHighlight && (
          <button type="button" onClick={onDismissHighlight} className="text-[10px] text-muted hover:text-foreground">
            dismiss
          </button>
        )}
      </header>
      <p className="mt-1 text-foreground">{entry.shortDefinition}</p>
      <p className="mt-1 text-muted">
        <span className="text-foreground/80">Why it matters: </span>
        {entry.whyItMatters}
      </p>
      <p className="mt-1 text-muted">
        <span className="text-foreground/80">How the desk uses it: </span>
        {entry.howDeskUsesIt}
      </p>
      {entry.interpretation && (
        <p className="mt-1 text-muted">
          <span className="text-foreground/80">Interpretation: </span>
          {entry.interpretation}
        </p>
      )}
    </article>
  );
}
