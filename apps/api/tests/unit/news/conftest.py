from datetime import datetime, timezone


def et(*args, **kwargs) -> datetime:
    """Build a UTC-aware datetime -- events/reaction tests don't need
    exchange-local time, just deterministic, unambiguous timestamps."""
    if kwargs.get("tzinfo") is None:
        kwargs["tzinfo"] = timezone.utc
    return datetime(*args, **kwargs)


def raw_article(headline, published_at, symbols, source="Reuters", raw_category=None, url=None):
    return {
        "headline": headline,
        "published_at": published_at.isoformat(),
        "symbols": symbols,
        "source": source,
        "raw_category": raw_category,
        "url": url,
    }
