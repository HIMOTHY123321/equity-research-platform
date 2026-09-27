"""The monitoring universe (§8/§22): which symbols the background monitor
scans, independent of mere Watchlist membership. Persisted via
MonitoringSubscriptionRecord (through AlertRepository) rather than
hard-coded, and seeded from a fixed default symbol list the first time it
is empty -- never SPY/QQQ/NVDA-only.

Phase 16 (§9/§97): this seed is now a plain constant, not a live
Watchlist lookup. MonitoringSubscriptionRecord is genuinely global/shared
(one server-wide "which symbols does the Decision Engine actively scan"
universe), while Watchlist is now per-user (see
app.watchlist.repository.SqlAlchemyWatchlistRepository) -- coupling a
global background service's seed to any one user's personal watchlist
would either pick an arbitrary user or require this class to run in a
request context it doesn't have (this seed also runs from the FastAPI
lifespan, entirely outside any HTTP request/user). A future refinement
could seed from the union of every user's watchlist instead; deferred and
disclosed rather than half-implemented under time pressure.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.alerts.repository import AlertRepository
from app.alerts.schemas import MonitoringSubscription
from app.watchlist.repository import DEFAULT_WATCHLIST_SYMBOLS


class MonitoringUniverse:
    def __init__(
        self, repository: AlertRepository, default_symbols: tuple[str, ...] = DEFAULT_WATCHLIST_SYMBOLS
    ) -> None:
        self._repository = repository
        self._default_symbols = default_symbols

    def list_enabled_symbols(self) -> list[str]:
        """The set of symbols the monitor actually scans. Seeds itself from
        `default_symbols` exactly once, the first time no subscriptions exist
        at all, so a fresh deployment still monitors something without
        hard-coding a fixed ticker list; after that, this table alone is the
        source of truth and Watchlist membership no longer implies
        monitoring."""
        subscriptions = self._repository.list_monitoring_subscriptions()
        if not subscriptions:
            subscriptions = self._seed_defaults()
        return sorted(s.symbol for s in subscriptions if s.enabled and s.decision_monitoring_enabled)

    def is_monitored(self, symbol: str) -> bool:
        return symbol in self.list_enabled_symbols()

    def list_all_subscriptions(self) -> list[MonitoringSubscription]:
        """Every subscription regardless of enabled state -- seeds from the
        Watchlist first, same as list_enabled_symbols, so the UI can show a
        disabled row rather than nothing at all."""
        subscriptions = self._repository.list_monitoring_subscriptions()
        if not subscriptions:
            subscriptions = self._seed_defaults()
        return sorted(subscriptions, key=lambda s: s.symbol)

    def enable(self, symbol: str, *, preferred_timeframes: list[str] | None = None) -> MonitoringSubscription:
        existing = self._find(symbol)
        subscription = MonitoringSubscription(
            symbol=symbol,
            enabled=True,
            decision_monitoring_enabled=True,
            preferred_timeframes=preferred_timeframes or (existing.preferred_timeframes if existing else []),
            added_at=existing.added_at if existing else datetime.now(timezone.utc),
        )
        self._repository.upsert_monitoring_subscription(subscription)
        return subscription

    def disable(self, symbol: str) -> None:
        existing = self._find(symbol)
        if existing is None:
            return
        self._repository.upsert_monitoring_subscription(existing.model_copy(update={"enabled": False}))

    def _find(self, symbol: str) -> MonitoringSubscription | None:
        # Regression (Phase 14.1): must seed-if-empty the same way
        # list_enabled_symbols/list_all_subscriptions do -- otherwise
        # disable() on a symbol before the universe has ever been listed
        # silently no-ops (the table looks empty, so `existing is None`,
        # so disable() returns without writing anything).
        for s in self.list_all_subscriptions():
            if s.symbol == symbol:
                return s
        return None

    def _seed_defaults(self) -> list[MonitoringSubscription]:
        now = datetime.now(timezone.utc)
        seeded = []
        for ticker in self._default_symbols:
            subscription = MonitoringSubscription(symbol=ticker, enabled=True, added_at=now)
            self._repository.upsert_monitoring_subscription(subscription)
            seeded.append(subscription)
        return seeded
