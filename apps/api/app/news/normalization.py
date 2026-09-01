"""Provider-independent article normalization (#B). Every NewsProvider
implementation builds its NormalizedNewsArticle objects through
`build_normalized_article` -- no provider-specific dict shape is ever
constructed or consumed outside app.news.*_provider modules.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from app.news.classification import classify_article
from app.news.schemas import NormalizedNewsArticle
from app.schemas.symbols import InvalidTickerError, normalize_ticker


def compute_article_id(
    provider: str, source: Optional[str], headline: str, published_at: datetime, url: Optional[str]
) -> str:
    """Stable, content-derived id (#B, #L) -- re-ingesting the same source
    article (same provider/source/headline/timestamp/url) always produces
    the same id, so repository upserts are naturally idempotent without
    depending on a provider-supplied id that may not exist or be stable
    across re-fetches. Same sha256-hex-digest convention as
    app.research.provenance.compute_candle_data_hash."""
    digest_source = "|".join(
        [
            provider,
            source or "",
            headline.strip(),
            published_at.astimezone(timezone.utc).isoformat(),
            url or "",
        ]
    )
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]


def normalize_symbols(raw_symbols: list[str]) -> tuple[str, ...]:
    """Normalizes what it can, silently drops what it can't (#B: "never
    replace missing values with fake defaults" -- an unparseable symbol is
    simply not included, never guessed at). Order-preserving, deduplicated."""
    seen: list[str] = []
    for raw in raw_symbols:
        try:
            ticker = normalize_ticker(raw)
        except InvalidTickerError:
            continue
        if ticker not in seen:
            seen.append(ticker)
    return tuple(seen)


def build_normalized_article(
    *,
    provider: str,
    source: Optional[str],
    headline: str,
    published_at: datetime,
    received_at: Optional[datetime] = None,
    url: Optional[str] = None,
    raw_symbols: Optional[list[str]] = None,
    raw_category: Optional[str] = None,
    provenance: Optional[dict] = None,
    ingested_at: Optional[datetime] = None,
) -> NormalizedNewsArticle:
    if not headline or not headline.strip():
        raise ValueError("Article headline is required and cannot be blank")
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    if received_at is not None and received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    symbols = normalize_symbols(raw_symbols or [])
    classification = classify_article(headline, raw_category)
    article_id = compute_article_id(provider, source, headline, published_at, url)

    return NormalizedNewsArticle(
        article_id=article_id,
        provider=provider,
        source=source,
        headline=headline.strip(),
        published_at=published_at,
        received_at=received_at,
        url=url,
        symbols=symbols,
        raw_category=raw_category,
        classification=classification,
        provenance=provenance or {},
        ingested_at=ingested_at or datetime.now(timezone.utc),
    )
