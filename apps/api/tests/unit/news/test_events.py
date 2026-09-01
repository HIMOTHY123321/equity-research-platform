from app.news.config import DEFAULT_CATALYST_CONFIG
from app.news.events import group_into_events, headline_similarity
from app.news.fixture_provider import FixtureNewsProvider
from app.news.schemas import CatalystCategory
from tests.unit.news.conftest import et, raw_article


def _articles(raw):
    provider = FixtureNewsProvider(raw)
    far_future = et(2030, 1, 1)
    return provider.fetch_market_news(et(2000, 1, 1), far_future, far_future)


def test_same_event_from_multiple_sources_groups_together():
    raw = [
        raw_article(
            "Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"], source="Reuters"
        ),
        raw_article(
            "Acme Q2 earnings per share top estimates", et(2026, 8, 20, 9, 5), ["ACME"], source="Bloomberg"
        ),
        raw_article(
            "Acme quarterly earnings: what analysts are saying",
            et(2026, 8, 20, 12, 0),
            ["ACME"],
            source="CNBC",
        ),
    ]
    events = group_into_events(_articles(raw))
    assert len(events) == 1
    assert events[0].source_count == 3
    assert len(events[0].contributing_article_ids) == 3
    assert events[0].category == CatalystCategory.EARNINGS


def test_unrelated_events_close_in_time_stay_separate_by_category():
    raw = [
        raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"]),
        raw_article("Acme unveils new product launch", et(2026, 8, 20, 9, 5), ["ACME"]),
    ]
    events = group_into_events(_articles(raw))
    assert len(events) == 2
    categories = {e.category for e in events}
    assert categories == {CatalystCategory.EARNINGS, CatalystCategory.PRODUCT_LAUNCH}


def test_unrelated_events_close_in_time_stay_separate_by_symbol():
    raw = [
        raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"]),
        raw_article("Beta reports quarterly earnings beat", et(2026, 8, 20, 9, 5), ["BETA"]),
    ]
    events = group_into_events(_articles(raw))
    assert len(events) == 2
    assert {e.affected_symbols for e in events} == {("ACME",), ("BETA",)}


def test_article_outside_anchored_window_starts_a_new_event():
    """Grouping is anchored to the group's own earliest article, not
    sliding from article to article -- explicitly not "close in time"."""
    raw = [
        raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 0, 0), ["ACME"]),
        raw_article("Acme Q2 earnings follow-up coverage", et(2026, 8, 20, 10, 0), ["ACME"]),
        # 20h after the FIRST article (anchor) -- outside the 12h window
        # from the anchor, even though it's within 12h of the 2nd member.
        raw_article("Acme quarterly earnings analyst reactions", et(2026, 8, 20, 20, 0), ["ACME"]),
    ]
    events = group_into_events(_articles(raw))
    assert len(events) == 2
    assert len(events[0].contributing_article_ids) == 2
    assert len(events[1].contributing_article_ids) == 1


def test_event_ids_are_stable_and_order_independent():
    raw = [
        raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"]),
        raw_article("Acme Q2 earnings per share top estimates", et(2026, 8, 20, 9, 5), ["ACME"]),
    ]
    events_forward = group_into_events(_articles(raw))
    events_reversed = group_into_events(list(reversed(_articles(raw))))
    assert events_forward[0].event_id == events_reversed[0].event_id


def test_empty_article_list_produces_no_events():
    assert group_into_events([]) == []


def test_every_source_article_preserved_never_discarded():
    raw = [
        raw_article(
            "Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"], source="Reuters"
        ),
        raw_article(
            "Acme Q2 earnings per share top estimates", et(2026, 8, 20, 9, 5), ["ACME"], source="Bloomberg"
        ),
    ]
    events = group_into_events(_articles(raw))
    assert len(events) == 1
    assert events[0].source_count == 2


# ---- Phase 10.1 (#D) event-grouping hardening: UNKNOWN-category gate -------


def test_headline_similarity_identical_headlines_is_one():
    h = "Acme Corp shakes up leadership team amid strategy shift"
    assert headline_similarity(h, h) == 1.0


def test_headline_similarity_no_overlap_is_zero():
    assert headline_similarity("Acme unveils charity gala", "Zorp announces weather report") == 0.0


def test_headline_similarity_empty_headline_is_zero():
    assert headline_similarity("", "Acme Corp news") == 0.0


def test_related_unknown_stories_from_different_publications_merge():
    """Both classify UNKNOWN (no keyword rule matches either headline), but
    they clearly describe the same underlying story and share enough
    headline tokens to clear the similarity gate -- must still merge."""
    raw = [
        raw_article(
            "Acme Corp shakes up leadership team amid strategy shift",
            et(2026, 8, 20, 9, 0),
            ["ACME"],
            source="Reuters",
        ),
        raw_article(
            "Acme Corp leadership shakeup signals new strategy",
            et(2026, 8, 20, 9, 30),
            ["ACME"],
            source="Bloomberg",
        ),
    ]
    articles = _articles(raw)
    assert {a.classification.category for a in articles} == {CatalystCategory.UNKNOWN}
    events = group_into_events(articles)
    assert len(events) == 1
    assert events[0].source_count == 2


def test_unrelated_unknown_stories_same_ticker_do_not_merge_from_proximity_alone():
    """Both UNKNOWN, same symbol, well within the grouping window -- but
    headlines share almost nothing in common. Must stay separate (#D
    "false negatives are preferable to incorrectly combining unrelated
    corporate events")."""
    raw = [
        raw_article(
            "Acme Corp shakes up leadership team amid strategy shift",
            et(2026, 8, 20, 9, 0),
            ["ACME"],
        ),
        raw_article(
            "Acme Corp featured in local charity gala coverage",
            et(2026, 8, 20, 9, 30),
            ["ACME"],
        ),
    ]
    articles = _articles(raw)
    assert {a.classification.category for a in articles} == {CatalystCategory.UNKNOWN}
    similarity = headline_similarity(articles[0].headline, articles[1].headline)
    assert similarity < DEFAULT_CATALYST_CONFIG.unknown_category_min_headline_similarity

    events = group_into_events(articles)
    assert len(events) == 2


def test_known_category_grouping_unaffected_by_similarity_gate():
    """Two EARNINGS headlines sharing almost no tokens beyond the company
    name must still merge -- the similarity gate only ever applies to
    UNKNOWN-UNKNOWN pairs, never to a real matched category."""
    raw = [
        raw_article("Acme reports quarterly earnings beat", et(2026, 8, 20, 9, 0), ["ACME"]),
        raw_article("Acme Q2 earnings per share top estimates", et(2026, 8, 20, 9, 30), ["ACME"]),
    ]
    articles = _articles(raw)
    similarity = headline_similarity(articles[0].headline, articles[1].headline)
    events = group_into_events(articles)
    assert len(events) == 1  # merges regardless of how low `similarity` is
    assert similarity >= 0.0  # sanity: similarity was actually computed, not skipped


def test_unknown_gate_event_ids_remain_stable_and_order_independent():
    raw = [
        raw_article(
            "Acme Corp shakes up leadership team amid strategy shift", et(2026, 8, 20, 9, 0), ["ACME"]
        ),
        raw_article(
            "Acme Corp leadership shakeup signals new strategy", et(2026, 8, 20, 9, 30), ["ACME"]
        ),
    ]
    articles = _articles(raw)
    events_forward = group_into_events(articles)
    events_reversed = group_into_events(list(reversed(articles)))
    assert events_forward[0].event_id == events_reversed[0].event_id
