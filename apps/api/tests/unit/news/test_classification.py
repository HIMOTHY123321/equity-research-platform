from app.news.classification import classify_article
from app.news.schemas import CatalystCategory, ClassificationBasis, ClassificationMethod


def test_provider_category_direct_map_takes_priority():
    result = classify_article("Acme announces something", "earnings")
    assert result.category == CatalystCategory.EARNINGS
    assert result.basis == ClassificationBasis.PROVIDER_CATEGORY_DIRECT_MAP
    assert result.provider_raw_category == "earnings"


def test_strong_keyword_match():
    result = classify_article("Acme Corp reports quarterly earnings beat estimates", None)
    assert result.category == CatalystCategory.EARNINGS
    assert result.basis == ClassificationBasis.STRONG_KEYWORD_MATCH
    assert result.matched_rules


def test_more_specific_category_wins_over_broader_one():
    """EARNINGS_PREANNOUNCEMENT is checked before EARNINGS -- a headline
    matching both must resolve to the more specific category."""
    result = classify_article("Acme preannounces earnings shortfall", None)
    assert result.category == CatalystCategory.EARNINGS_PREANNOUNCEMENT


def test_weak_fallback_when_no_strong_phrase_matches():
    result = classify_article("Analyst comments on the stock today", None)
    assert result.category == CatalystCategory.ANALYST_RATING
    assert result.basis == ClassificationBasis.WEAK_KEYWORD_FALLBACK


def test_unknown_when_nothing_matches():
    result = classify_article("A completely unrelated headline about weather", None)
    assert result.category == CatalystCategory.UNKNOWN
    assert result.basis == ClassificationBasis.UNKNOWN_NO_MATCH
    assert result.matched_rules == []


def test_classification_method_is_always_deterministic_rule():
    result = classify_article("Acme reports quarterly earnings", None)
    assert result.method == ClassificationMethod.DETERMINISTIC_RULE


def test_unmapped_provider_category_falls_through_to_keyword_rules():
    result = classify_article("Acme upgrades outlook after strong quarter", "STORY")
    assert result.provider_raw_category == "STORY"
    assert result.category != CatalystCategory.UNKNOWN


def test_no_fake_confidence_field_exists():
    """Classification never fabricates a numeric confidence score -- only a
    discrete, inspectable basis tier (#M "no fake confidence")."""
    result = classify_article("Acme reports quarterly earnings", None)
    assert not hasattr(result, "confidence")
    assert isinstance(result.basis, ClassificationBasis)


def test_classification_is_case_insensitive():
    upper = classify_article("ACME REPORTS QUARTERLY EARNINGS BEAT", None)
    lower = classify_article("acme reports quarterly earnings beat", None)
    assert upper.category == lower.category == CatalystCategory.EARNINGS
