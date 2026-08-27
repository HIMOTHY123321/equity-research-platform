from app.market_data.cache import InMemoryCache


def test_returns_none_for_missing_key():
    cache = InMemoryCache()
    assert cache.get("missing") is None


def test_returns_value_before_expiry():
    now = [0.0]
    cache = InMemoryCache(clock=lambda: now[0])

    cache.set("k", "v", ttl_seconds=10)
    now[0] = 5.0

    assert cache.get("k") == "v"


def test_expires_after_ttl():
    now = [0.0]
    cache = InMemoryCache(clock=lambda: now[0])

    cache.set("k", "v", ttl_seconds=10)
    now[0] = 10.0

    assert cache.get("k") is None


def test_clear_removes_all_entries():
    cache = InMemoryCache()
    cache.set("a", 1, ttl_seconds=100)
    cache.set("b", 2, ttl_seconds=100)

    cache.clear()

    assert cache.get("a") is None
    assert cache.get("b") is None
