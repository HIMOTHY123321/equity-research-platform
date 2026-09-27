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
lifespan, entirely outside any HTTP request/user).

Phase 16.1 (§5): this is now genuinely the SYSTEM RESEARCH UNIVERSE --
"which symbols need background computation at all" -- and it is
deliberately NOT the same question as "which alerts does a given user
receive" (see app.alerts.repository's `deliver_alert_to_subscribed_users`/
`UserAlertDeliveryRecord` for that). `list_enabled_symbols` is the union
of the fixed default seed, the legacy global `MonitoringSubscriptionRecord`
table (kept for any system/admin-pinned symbol), and the distinct set of
symbols at least one real user has actively subscribed to
(`UserMonitoringSubscriptionRecord` via
`AlertRepository.list_all_monitored_symbols`) -- so a symbol a user cares
about actually gets scanned, without ever conflating "the engine computes
this" with "this specific user gets alerted for it."
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
        """The SYSTEM RESEARCH UNIVERSE the monitor actually scans (Phase
        16.1 §5): the union of the legacy global subscriptions table
        (seeded from `default_symbols` exactly once, the first time it's
        empty, so a fresh deployment still monitors something) and every
        symbol at least one real user actively monitors. Deliberately NOT
        "which users get alerted for X" -- that's
        AlertRepository.deliver_alert_to_subscribed_users, a completely
        separate, per-user question."""
        subscriptions = self._repository.list_monitoring_subscriptions()
        if not subscriptions:
            subscriptions = self._seed_defaults()
        system_symbols = {s.symbol for s in subscriptions if s.enabled and s.decision_monitoring_enabled}
        user_symbols = set(self._repository.list_all_monitored_symbols())
        return sorted(system_symbols | user_symbols)

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
