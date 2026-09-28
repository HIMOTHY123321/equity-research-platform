"""The background monitor (§11): the thing that finally starts the Decision
Engine across a whole configurable universe of symbols instead of only ever
reacting to a manual `/scan` click on whatever symbol happens to be open.

`scan_once` is the directly-testable synchronous core (same shape as
ForecastMonitor.scan_and_resolve_once / DecisionEngineService.evaluate_open_
plans_for): one pass over every enabled MonitoringUniverse symbol, calling
the SAME `run_symbol_scan` the manual `/scan` route uses (§6 -- zero
Decision Engine logic lives here, this module only detects and reacts),
turning every resulting DecisionTransition into an AlertEvent via
AlertService, and broadcasting DecisionStateChangeEvent for every
transition (alert-worthy or not, e.g. ABSTAIN) plus MonitorStatusEvent for
symbol-level failures (§45 failure isolation -- one bad symbol never stops
the rest).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.resolver import resolve_pending_horizon_outcomes, resolve_pending_outcomes
from app.alerts.schemas import AlertOrigin, AlertType
from app.alerts.service import AlertEventBus, AlertService
from app.decision_engine.repository import DecisionEngineRepository, SqlAlchemyDecisionEngineRepository
from app.decision_engine.schemas import DecisionTransition
from app.decision_engine.service import run_symbol_scan
from app.live.config import (
    DEFAULT_LIVE_CONFIG,
    FreshnessState,
    LiveConfig,
    SubscriptionPriority,
    classify_freshness,
)
from app.live.market_hours import current_live_session
from app.live.service import LiveMarketService
from app.market_data.provider import MarketDataProvider
from app.monitoring.universe import MonitoringUniverse
from app.schemas.market_data import Timeframe
from app.watchlist.repository import DEFAULT_WATCHLIST_SYMBOLS

logger = logging.getLogger(__name__)

# Symbols in the monitoring universe are scanned on whatever timeframes
# they've configured, defaulting to this when none is set -- matches the
# Decision Monitor UI's own default (`?timeframe=1h` in the manual scan
# route) so a freshly-monitored symbol without preferences behaves exactly
# like clicking "scan" on it manually would have.
_DEFAULT_TIMEFRAMES = (Timeframe.ONE_HOUR,)


@dataclass(frozen=True)
class DecisionStateChangeEvent:
    """Broadcast for every DecisionTransition the monitor observes,
    independent of whether it produced an AlertEvent (e.g. ABSTAIN) --
    lets a connected UI reflect state immediately without waiting on the
    (preference-gated) alert stream."""

    decision_plan_id: str
    symbol: str
    from_state: Optional[str]
    to_state: str
    occurred_at: datetime


@dataclass(frozen=True)
class MonitorStatusEvent:
    symbol: str
    status: str  # "ok" | "error"
    detail: str
    at: datetime


class MonitoringService:
    """Owns no long-lived Session -- same "fresh session per pass, closed
    when the pass ends" convention as ForecastMonitor/NewsMonitor (a
    Session held open for the lifetime of a background asyncio task would
    drift from what other request-scoped sessions have since committed).
    `event_bus` is the one thing that DOES persist across passes: it is
    handed to a freshly-constructed AlertService every scan, so a WebSocket
    connection's listener queue (registered once, at connect time) keeps
    receiving alerts no matter which pass emitted them."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        market_provider: MarketDataProvider,
        event_bus: Optional[AlertEventBus] = None,
        config: LiveConfig = DEFAULT_LIVE_CONFIG,
        now_fn=lambda: datetime.now(timezone.utc),
        default_symbols: tuple[str, ...] = DEFAULT_WATCHLIST_SYMBOLS,
        live_service: Optional[LiveMarketService] = None,
    ) -> None:
        self._session_factory = session_factory
        self._market_provider = market_provider
        self._default_symbols = default_symbols
        self.event_bus = event_bus or AlertEventBus()
        self._config = config
        self._now = now_fn
        self._task: Optional[asyncio.Task] = None
        # Phase 19 (§1/§2): the SYSTEM RESEARCH UNIVERSE already computed
        # here is the exact "server-side demand" that should drive
        # streaming subscriptions -- so genuine real-time data is always
        # flowing for every actively-researched symbol, never gated on a
        # user happening to have a browser tab open. `None` (default, and
        # what every existing test constructs) means this reconciliation
        # is simply skipped -- streaming-optional deployments and the
        # existing synchronous `scan_once` tests are unaffected.
        self._live_service = live_service
        self._live_subscribed: set[str] = set()
        self._listeners: list[
            "asyncio.Queue[DecisionStateChangeEvent | MonitorStatusEvent]"
        ] = []
        # §6: transition-based, in-process memory of each symbol's last
        # observed freshness state. Deliberately NOT persisted -- after a
        # restart this starts empty again, and the first observation for a
        # symbol only ever seeds the cache (never alerts), so a symbol that
        # was already stale before restart does not get a duplicate
        # DATA_STALE the moment the process comes back up. The DB dedup key
        # (time-bucketed) is the secondary, persisted safety net.
        self._freshness_by_symbol: dict[str, FreshnessState] = {}

    def add_listener(self) -> "asyncio.Queue[DecisionStateChangeEvent | MonitorStatusEvent]":
        queue: "asyncio.Queue[DecisionStateChangeEvent | MonitorStatusEvent]" = asyncio.Queue()
        self._listeners.append(queue)
        return queue

    def remove_listener(
        self, queue: "asyncio.Queue[DecisionStateChangeEvent | MonitorStatusEvent]"
    ) -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def _emit(self, event) -> None:
        for queue in list(self._listeners):
            queue.put_nowait(event)

    def _check_freshness_transition(
        self, symbol: str, snapshot, as_of: datetime, alert_service: AlertService
    ) -> None:
        """§28: DATA_STALE emitted once on the fresh->stale transition,
        DATA_RECOVERED once on stale->fresh -- reuses the exact same
        deterministic `classify_freshness` every other live-data surface
        uses (app.live.config), never a second freshness judgment call."""
        latest_candle = snapshot.feature_snapshot.latest_candle if snapshot.feature_snapshot else None
        if latest_candle is None:
            return
        age_seconds = max((as_of - latest_candle.timestamp).total_seconds(), 0.0)
        session = current_live_session(as_of)
        current_state = classify_freshness(age_seconds, connected=True, session=session, config=self._config)

        previous_state = self._freshness_by_symbol.get(symbol)
        self._freshness_by_symbol[symbol] = current_state
        if previous_state is None or previous_state == current_state:
            return

        # A short cooldown, not the default 1-hour one: the transition
        # check above is the real throttle (only ever called on an actual
        # fresh<->stale crossing), so the dedup key here only needs to
        # guard against re-emitting the exact same instant twice, never
        # collapse two genuinely separate stale episodes within the hour.
        transition_cooldown = timedelta(seconds=1)
        if current_state == FreshnessState.STALE and previous_state != FreshnessState.STALE:
            alert_service.emit_condition_alert(
                symbol=symbol,
                alert_type=AlertType.DATA_STALE,
                identity="freshness",
                title="Data stale",
                summary=f"{symbol} market data has not refreshed within the expected window.",
                source_timestamp=as_of,
                origin=AlertOrigin.LIVE_PROSPECTIVE,
                data_freshness_state=current_state.value,
                cooldown=transition_cooldown,
            )
        elif previous_state == FreshnessState.STALE and current_state != FreshnessState.STALE:
            alert_service.emit_condition_alert(
                symbol=symbol,
                alert_type=AlertType.DATA_RECOVERED,
                identity="freshness",
                title="Data recovered",
                summary=f"{symbol} market data has resumed refreshing normally.",
                source_timestamp=as_of,
                origin=AlertOrigin.LIVE_PROSPECTIVE,
                data_freshness_state=current_state.value,
                cooldown=transition_cooldown,
            )

    def scan_symbol_once(
        self,
        symbol: str,
        timeframe: Timeframe,
        as_of: datetime,
        decision_repository: DecisionEngineRepository,
        alert_service: AlertService,
    ) -> list[DecisionTransition]:
        """One symbol/timeframe pass: scan, then turn every resulting
        transition into a DecisionStateChangeEvent broadcast plus (when
        alert-worthy) an AlertEvent. A provider failure on this symbol is
        caught and reported via MonitorStatusEvent -- it never propagates
        and never stops the caller's loop over the rest of the universe
        (§45)."""
        try:
            result = run_symbol_scan(symbol, timeframe, self._market_provider, decision_repository, as_of)
        except Exception as exc:  # noqa: BLE001 -- deliberate: one bad symbol must not stop the rest
            logger.exception("Monitoring scan failed for %s", symbol)
            self._emit(MonitorStatusEvent(symbol=symbol, status="error", detail=str(exc), at=self._now()))
            return []

        self._emit(MonitorStatusEvent(symbol=symbol, status="ok", detail="scan completed", at=self._now()))
        self._check_freshness_transition(symbol, result.snapshot, as_of, alert_service)

        plan_by_id = {p.decision_plan_id: p for p in result.plans}
        all_transitions = [
            *(t for plan in result.new_plans for t in plan.transitions),
            *result.transitions,
        ]
        for transition in all_transitions:
            self._emit(
                DecisionStateChangeEvent(
                    decision_plan_id=transition.decision_plan_id,
                    symbol=symbol,
                    from_state=transition.from_state.value if transition.from_state else None,
                    to_state=transition.to_state.value,
                    occurred_at=transition.occurred_at,
                )
            )
            plan = plan_by_id.get(transition.decision_plan_id)
            if plan is not None:
                alert_service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

        return all_transitions

    def scan_once(self) -> list[DecisionTransition]:
        """One full pass over the whole enabled monitoring universe (§8/§9).
        Symbol failure isolation applies per-symbol inside
        scan_symbol_once; this loop itself never stops early. Opens exactly
        one Session for the whole pass, closed when the pass ends."""
        as_of = self._now()
        session = self._session_factory()
        try:
            alert_repository = SqlAlchemyAlertRepository(session)
            decision_repository = SqlAlchemyDecisionEngineRepository(session)
            universe = MonitoringUniverse(alert_repository, self._default_symbols)
            alert_service = AlertService(alert_repository, event_bus=self.event_bus)

            transitions: list[DecisionTransition] = []
            for symbol in universe.list_enabled_symbols():
                for timeframe in _DEFAULT_TIMEFRAMES:
                    transitions.extend(
                        self.scan_symbol_once(symbol, timeframe, as_of, decision_repository, alert_service)
                    )

            # §33/§Phase-14.1-3: every pass also attempts to resolve any
            # eligible prospective alert that doesn't have an outcome yet --
            # the only place future data enters this package. Failures here
            # (e.g. a provider error resolving one alert) must not prevent
            # the rest of the monitoring pass from having already
            # completed above, so they're caught and logged, never raised.
            try:
                resolve_pending_outcomes(
                    alert_repository, decision_repository, self._market_provider, now=as_of
                )
            except Exception:  # noqa: BLE001 -- deliberate: resolution failures must not crash the loop
                logger.exception("Prospective outcome resolution pass failed")

            # Phase 15: independent per-horizon resolution runs alongside
            # the all-or-nothing pass above -- a symbol that hasn't yet
            # accumulated the full 20-bar window can still have its
            # 1/3/5/10-bar horizons resolved and persisted here.
            try:
                resolve_pending_horizon_outcomes(
                    alert_repository, decision_repository, self._market_provider, now=as_of
                )
            except Exception:  # noqa: BLE001 -- deliberate: resolution failures must not crash the loop
                logger.exception("Prospective per-horizon outcome resolution pass failed")

            return transitions
        finally:
            session.close()

    # ---------------------------------------------------- live subscription sync

    async def _sync_live_subscriptions(self) -> None:
        """Phase 19 (§1/§2): reconciles `LiveMarketService`'s
        `BACKGROUND_BENCHMARK`-priority subscriptions against the current
        SYSTEM RESEARCH UNIVERSE. Ref-counted at the priority level (see
        `LiveMarketService.subscribe`/`unsubscribe`), so a symbol also
        viewed live by an open browser tab (VIEWED priority) is unaffected
        by this reconciler adding/removing its OWN independent count --
        and 25 users monitoring NVDA still produces exactly one upstream
        provider subscription, never 25 (the existing ref-counting this
        reuses, not new per-symbol duplication). No-ops entirely when no
        `live_service` was configured (streaming-optional deployments)."""
        if self._live_service is None:
            return
        session = self._session_factory()
        try:
            alert_repository = SqlAlchemyAlertRepository(session)
            universe = MonitoringUniverse(alert_repository, self._default_symbols)
            current = set(universe.list_enabled_symbols())
        finally:
            session.close()

        added = current - self._live_subscribed
        removed = self._live_subscribed - current
        for symbol in added:
            try:
                await self._live_service.subscribe(symbol, priority=SubscriptionPriority.BACKGROUND_BENCHMARK)
            except Exception:  # noqa: BLE001 -- one bad symbol must not stop the rest
                logger.exception("Live subscription sync failed to subscribe %s", symbol)
                continue
            self._live_subscribed.add(symbol)
        for symbol in removed:
            try:
                await self._live_service.unsubscribe(
                    symbol, priority=SubscriptionPriority.BACKGROUND_BENCHMARK
                )
            except Exception:  # noqa: BLE001
                logger.exception("Live subscription sync failed to unsubscribe %s", symbol)
                continue
            self._live_subscribed.discard(symbol)

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        # Phase 19: reconcile once immediately so streaming begins at
        # startup rather than waiting a full scan interval.
        await self._sync_live_subscriptions()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        try:
            while True:
                try:
                    await asyncio.to_thread(self.scan_once)
                except Exception:
                    logger.exception("Monitoring service scan pass failed")
                try:
                    await self._sync_live_subscriptions()
                except Exception:
                    logger.exception("Live subscription sync pass failed")
                await asyncio.sleep(self._config.forecast_monitor_interval_seconds)
        except asyncio.CancelledError:
            return
