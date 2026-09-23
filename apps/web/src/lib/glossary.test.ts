import { describe, expect, it } from "vitest";

import {
  GLOSSARY_CATEGORIES,
  GLOSSARY_TERMS,
  getGlossaryCategory,
  getGlossaryTerm,
  searchGlossary,
  termsInCategory,
} from "./glossary";

describe("glossary data integrity", () => {
  it("has unique ids across every entry", () => {
    const ids = GLOSSARY_TERMS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("assigns every entry to a real category", () => {
    const categoryIds = new Set(GLOSSARY_CATEGORIES.map((c) => c.id));
    for (const entry of GLOSSARY_TERMS) {
      expect(categoryIds.has(entry.category)).toBe(true);
    }
  });

  it("every related id (where present) resolves to a real entry", () => {
    for (const entry of GLOSSARY_TERMS) {
      for (const relatedId of entry.related ?? []) {
        expect(getGlossaryTerm(relatedId), `${entry.id} -> related "${relatedId}"`).not.toBeNull();
      }
    }
  });
});

describe("getGlossaryTerm", () => {
  it("resolves a known id", () => {
    expect(getGlossaryTerm("break-of-structure")?.term).toBe("Break of Structure");
  });

  it("fails safely (returns null, never throws) for an unknown id", () => {
    expect(() => getGlossaryTerm("not-a-real-term-id")).not.toThrow();
    expect(getGlossaryTerm("not-a-real-term-id")).toBeNull();
  });
});

describe("getGlossaryCategory", () => {
  it("resolves a known category id", () => {
    expect(getGlossaryCategory("trading_basics")?.label).toBe("Trading Basics");
  });
});

describe("termsInCategory", () => {
  it("returns only terms in the requested category, alphabetically ordered", () => {
    const terms = termsInCategory("support_resistance");
    expect(terms.length).toBeGreaterThan(0);
    expect(terms.every((t) => t.category === "support_resistance")).toBe(true);
    const names = terms.map((t) => t.term);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
  });
});

describe("searchGlossary", () => {
  it("matches by abbreviation (BOS -> Break of Structure)", () => {
    const results = searchGlossary("BOS");
    expect(results.some((t) => t.id === "break-of-structure")).toBe(true);
  });

  it("matches by an alias/informal phrase in the definition text (structure break -> BOS/related)", () => {
    const results = searchGlossary("structure break");
    expect(results.length).toBeGreaterThan(0);
  });

  it("matches by full term text (volume -> RVOL / Volume Confirmation)", () => {
    const results = searchGlossary("volume");
    const ids = results.map((t) => t.id);
    expect(ids).toContain("relative-volume");
    expect(ids).toContain("volume-confirmation");
  });

  it("matches definition text alone, not just the term/abbreviation (excursion -> MFE/MAE)", () => {
    const results = searchGlossary("excursion");
    const ids = results.map((t) => t.id);
    expect(ids).toContain("maximum-favorable-excursion");
    expect(ids).toContain("maximum-adverse-excursion");
  });

  it("is case-insensitive", () => {
    const lower = searchGlossary("bos");
    const upper = searchGlossary("BOS");
    expect(lower.map((t) => t.id)).toEqual(upper.map((t) => t.id));
  });

  it("returns an empty array for an empty/whitespace query", () => {
    expect(searchGlossary("")).toEqual([]);
    expect(searchGlossary("   ")).toEqual([]);
  });

  it("returns an empty array when nothing matches", () => {
    expect(searchGlossary("zzz_not_a_real_query_zzz")).toEqual([]);
  });
});
