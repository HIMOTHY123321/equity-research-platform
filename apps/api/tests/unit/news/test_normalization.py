from datetime import datetime, timezone

import pytest

from app.news.normalization import build_normalized_article, compute_article_id, normalize_symbols


def test_normalizes_naive_timestamp_to_utc():
    article = build_normalized_article(
        provider="fixture",
        source="Reuters",
        headline="Acme reports earnings",
        published_at=datetime(2026, 8, 20, 14, 30),
        raw_symbols=["acme"],
    )
    assert article.published_at.tzinfo is not None
    assert article.published_at == datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc)


def test_missing_optional_fields_stay_none_not_fabricated():
    article = build_normalized_article(
        provider="fixture",
        source=None,
        headline="Some headline",
        published_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    assert article.source is None
    assert article.url is None
    assert article.received_at is None
    assert article.raw_category is None
    assert article.symbols == ()


def test_blank_headline_rejected():
    with pytest.raises(ValueError):
        build_normalized_article(
            provider="fixture",
            source="Reuters",
            headline="   ",
            published_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )


def test_normalize_symbols_drops_malformed_and_dedupes():
    result = normalize_symbols(["aapl", "AAPL", "not a ticker!", "msft", ""])
    assert result == ("AAPL", "MSFT")


def test_normalize_symbols_empty_list():
    assert normalize_symbols([]) == ()


def test_article_id_is_stable_for_identical_inputs():
    kwargs = dict(
        provider="fixture",
        source="Reuters",
        headline="Acme reports earnings",
        published_at=datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc),
        url="https://example.com/a",
    )
    id_a = compute_article_id(**kwargs)
    id_b = compute_article_id(**kwargs)
    assert id_a == id_b


def test_article_id_differs_for_different_content():
    base = dict(
        provider="fixture",
        source="Reuters",
        headline="Acme reports earnings",
        published_at=datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc),
        url="https://example.com/a",
    )
    id_a = compute_article_id(**base)
    id_b = compute_article_id(**{**base, "headline": "Acme reports different earnings"})
    assert id_a != id_b


def test_re_ingesting_same_raw_article_produces_same_article_id():
    """Idempotency at the normalization boundary (#L) -- the repository
    relies on this to make re-ingestion a safe no-op."""
    kwargs = dict(
        provider="fixture",
        source="Reuters",
        headline="Acme reports earnings",
        published_at=datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc),
        raw_symbols=["ACME"],
    )
    article_a = build_normalized_article(**kwargs)
    article_b = build_normalized_article(**kwargs)
    assert article_a.article_id == article_b.article_id
