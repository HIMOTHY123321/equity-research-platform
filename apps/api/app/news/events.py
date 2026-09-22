"""Deterministic catalyst event grouping/deduplication (#D).

Design note on as_of correctness (#E): `group_into_events` is a pure
function of whatever article set it is given -- it never reads a persisted
"event" row and never mutates one in place. A caller wanting historical
events "as of" some past instant T must first filter articles to
`published_at <= T` and then call this function fresh; because grouping is
deterministic given a fixed input set, that always reproduces byte-identical
`CatalystEvent`s regardless of how many *later* articles have since been
ingested. This is what makes "appending a future article never changes a
historical snapshot" true by construction rather than by a special case --
see tests/unit/news/test_as_of.py. The persisted `catalyst_events` table
(app.news.repository) is a materialized cache of the *current* (most
recent as_of) grouping for fast listing, never the source of truth for a
historical as_of query.

Grouping rule (explicitly anchored, not "close to the previous article" --
the product spec explicitly rejects merging purely on time proximity):
processing articles chronologically, a candidate article joins the first
still-open group whose anchor (the group's own earliest article) shares at
least one affected symbol, shares the same normalized category, and whose
`published_at` falls within `event_grouping_window_hours` of that anchor's
`published_at`. If several open groups match, the group whose anchor is
closest in time wins (ties broken by the group's anchor article_id for
determinism). No match -> a new single-article group (event) is opened.

Hardening (Phase 10.1 #D): "unknown" is not a real category -- it means
classification found no matching rule, not that two UNKNOWN articles are
about the same kind of thing. So when BOTH the anchor and the candidate
classify as `CatalystCategory.UNKNOWN`, category+symbol+window alone is not
treated as sufficient; `headline_similarity` (a normalized-token Jaccard
score) must also clear `config.unknown_category_min_headline_similarity`.
No KNOWN category's grouping behavior changes -- a real, deterministically
matched category is already a much stronger signal than headline text.
"""

from __future__ import annotations

import hashlib
import re

from app.news.config import DEFAULT_CATALYST_CONFIG, CatalystConfig
from app.news.relevance import classify_relevance
from app.news.schemas import CatalystCategory, CatalystEvent, NormalizedNewsArticle

# Common English function words carrying no distinguishing meaning for
# "are these two headlines about the same story" -- deliberately small and
# hand-maintained, same convention as app.news.classification's keyword
# lists, not an imported NLP stopword corpus.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "in", "on", "for", "to", "and", "or", "with",
        "by", "is", "are", "as", "at", "its", "it's", "from", "after",
        "over", "into", "amid", "than", "will", "has", "have", "had",
        "this", "that", "new", "says", "said",
    }
)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _normalized_tokens(headline: str) -> set[str]:
    words = _TOKEN_PATTERN.findall(headline.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def headline_similarity(a: str, b: str) -> float:
    """Jaccard similarity over normalized headline tokens -- 0.0 (nothing in
    common) to 1.0 (identical token sets). Used only to gate UNKNOWN-category
    grouping (#D); known-category grouping never consults this."""
    tokens_a, tokens_b = _normalized_tokens(a), _normalized_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _compute_event_id(article_ids: list[str]) -> str:
    """Deterministic: the same set of member articles always produces the
    same event_id, regardless of ingestion order (#D)."""
    digest_source = "|".join(sorted(article_ids))
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]


def _build_event(members: list[NormalizedNewsArticle]) -> CatalystEvent:
    ordered = sorted(members, key=lambda a: (a.published_at, a.article_id))
    anchor = ordered[0]
    article_ids = [a.article_id for a in ordered]
    symbols = tuple(sorted({s for a in ordered for s in a.symbols}))
    named_sources = {a.source for a in ordered if a.source}
    source_count = len(named_sources) if named_sources else len({a.provider for a in ordered})

    return CatalystEvent(
        event_id=_compute_event_id(article_ids),
        primary_timestamp=anchor.published_at,
        category=anchor.classification.category,
        affected_symbols=symbols,
        contributing_article_ids=article_ids,
        source_count=source_count,
        earliest_published_at=anchor.published_at,
        latest_update_at=ordered[-1].published_at,
        title=anchor.headline,
        provenance={"member_count": len(ordered)},
        relevance=classify_relevance(anchor.classification.category, anchor.headline),
        primary_source=anchor.source,
        primary_url=anchor.url,
    )


def group_into_events(
    articles: list[NormalizedNewsArticle],
    config: CatalystConfig = DEFAULT_CATALYST_CONFIG,
) -> list[CatalystEvent]:
    ordered = sorted(articles, key=lambda a: (a.published_at, a.article_id))
    groups: list[list[NormalizedNewsArticle]] = []

    for article in ordered:
        best_group = None
        best_gap_hours = None
        for group in groups:
            anchor = group[0]
            if anchor.classification.category != article.classification.category:
                continue
            group_symbols = {s for member in group for s in member.symbols}
            if not (group_symbols & set(article.symbols)):
                continue
            gap_hours = (article.published_at - anchor.published_at).total_seconds() / 3600.0
            if gap_hours < 0 or gap_hours > config.event_grouping_window_hours:
                continue
            if anchor.classification.category == CatalystCategory.UNKNOWN and (
                headline_similarity(anchor.headline, article.headline)
                < config.unknown_category_min_headline_similarity
            ):
                continue  # #D: category alone (UNKNOWN) is not a real signal
            if (
                best_gap_hours is None
                or gap_hours < best_gap_hours
                or (gap_hours == best_gap_hours and anchor.article_id < best_group[0].article_id)
            ):
                best_gap_hours = gap_hours
                best_group = group

        if best_group is not None:
            best_group.append(article)
        else:
            groups.append([article])

    events = [_build_event(group) for group in groups]
    events.sort(key=lambda e: (e.primary_timestamp, e.event_id))
    return events


def event_articles(
    event: CatalystEvent, articles_by_id: dict[str, NormalizedNewsArticle]
) -> list[NormalizedNewsArticle]:
    """Every source article behind an event, in publication order -- events
    never discard a member article (#D)."""
    members = [articles_by_id[aid] for aid in event.contributing_article_ids if aid in articles_by_id]
    return sorted(members, key=lambda a: (a.published_at, a.article_id))
