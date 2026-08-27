"""A deliberately tiny cache abstraction. Swap InMemoryCache for a Redis-backed
implementation later without touching CachedMarketDataProvider or routes.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class Cache(ABC):
    @abstractmethod
    def get(self, key: str) -> Any | None: ...

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: float) -> None: ...


class InMemoryCache(Cache):
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        self._store[key] = (self._clock() + ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()
