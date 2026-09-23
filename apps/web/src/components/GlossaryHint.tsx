"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { getGlossaryTerm } from "@/lib/glossary";

/**
 * FINAL TERMINAL POLISH PASS (#2): the one reusable "ⓘ" affordance every
 * help surface in the app uses -- chart legend, Setup Intelligence,
 * Research Lab, Forecast Lab, Historical Analogs, Catalyst Context,
 * Evidence Audit Trail, the live-data header. Always reads from the
 * centralized glossary (@/lib/glossary) -- never ships its own copy of a
 * definition. Fails safely (renders nothing) if `termId` doesn't resolve,
 * so a renamed/removed glossary entry can never crash the surface that
 * referenced it.
 */
export function GlossaryHint({
  termId,
  label,
  className = "",
}: {
  termId: string;
  /** Visible label before the ⓘ icon, e.g. "Relative Volume (RVOL)". If
   * omitted, only the icon is rendered (for compact/inline use). */
  label?: string;
  className?: string;
}) {
  const entry = getGlossaryTerm(termId);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement | null>(null);
  const popoverId = useId();

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(e: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  if (!entry) return null;

  return (
    <span ref={containerRef} className={`relative inline-flex items-center gap-1 ${className}`}>
      {label && <span>{label}</span>}
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={popoverId}
        aria-label={`What is ${entry.term}?`}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full border border-muted text-[9px] leading-none text-muted hover:border-accent hover:text-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
      >
        i
      </button>
      {open && (
        <span
          id={popoverId}
          role="dialog"
          aria-label={`${entry.term} definition`}
          className="absolute left-0 top-5 z-20 w-64 space-y-1.5 rounded border border-border bg-surface p-2.5 font-mono text-[10px] leading-snug text-foreground shadow-lg"
        >
          <span className="block font-semibold text-accent">
            {entry.term}
            {entry.abbreviation ? ` (${entry.abbreviation})` : ""}
          </span>
          <span className="block text-muted">{entry.shortDefinition}</span>
          <span className="block text-muted">{entry.whyItMatters}</span>
          <Link
            href={`/glossary?term=${entry.id}`}
            className="mt-1 inline-block text-accent underline"
            onClick={() => setOpen(false)}
          >
            Learn more
          </Link>
        </span>
      )}
    </span>
  );
}
