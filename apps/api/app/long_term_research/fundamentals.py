"""Fundamentals data abstraction for Long-Term Research -- a genuinely
new capability (no fundamentals/financial-statement provider existed
anywhere in this codebase before this feature; confirmed by inspection of
app.market_data and app.news, which only ever call yfinance's
`.history()` for candles). Follows the exact same ABC + concrete-
implementation pattern as app.market_data.provider.MarketDataProvider so
it is swappable the same way, via app.api.deps.get_fundamentals_provider
and `settings.fundamentals_provider` -- never hard-coded elsewhere.

Known, documented limitations of the yfinance-backed implementation (not
silently hidden, see the final Phase report):
- `.info` and `.quarterly_financials`/`.quarterly_income_stmt` coverage
  varies wildly by symbol. A recent IPO/SPAC/foreign-listed ADR can
  legitimately return almost nothing -- every field here is Optional and
  this provider NEVER invents a value for a field yfinance didn't supply.
- Analyst growth estimates are deliberately NOT read at all: yfinance's
  `.info` growth-estimate fields are not reliably timestamped or sourced
  per-estimate, and the spec for this feature explicitly says never to
  invent/use an estimate that isn't "genuinely sourced and timestamped."
- No forward-looking data of any kind is read -- only trailing/historical
  figures, which is what the anti-lookahead discipline the rest of this
  codebase already enforces (app.ai_analysis's cutoff-field pattern)
  requires.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Optional

from app.long_term_research.schemas import FundamentalsSnapshot

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 2


class FundamentalsProviderError(RuntimeError):
    """A genuine provider-level failure (network/rate-limit) -- distinct
    from "this symbol simply has no reported fundamentals," which is
    represented by Optional/empty fields on a successfully-returned
    FundamentalsSnapshot, never by raising."""


class FundamentalsProvider(ABC):
    @abstractmethod
    def get_fundamentals(self, symbol: str) -> FundamentalsSnapshot: ...


class FixtureFundamentalsProvider(FundamentalsProvider):
    """Deterministic, in-memory, test/dev-only provider -- returns exactly
    the FundamentalsSnapshot it was handed for a symbol, or an
    all-missing snapshot for any symbol not explicitly seeded. Never
    touches the network."""

    def __init__(self, snapshots: Optional[dict[str, FundamentalsSnapshot]] = None) -> None:
        self._snapshots = dict(snapshots or {})

    def set_snapshot(self, symbol: str, snapshot: FundamentalsSnapshot) -> None:
        self._snapshots[symbol] = snapshot

    def get_fundamentals(self, symbol: str) -> FundamentalsSnapshot:
        if symbol in self._snapshots:
            return self._snapshots[symbol]
        return FundamentalsSnapshot(
            symbol=symbol, fetched_at=datetime.now(timezone.utc), provider="fixture"
        )


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    return parsed


class YFinanceFundamentalsProvider(FundamentalsProvider):
    """`ticker_factory` is injectable (defaults to the real `yfinance.
    Ticker`) so tests never touch the network -- the exact same
    convention app.market_data.yfinance_provider.YFinanceMarketDataProvider
    already uses."""

    def __init__(
        self,
        ticker_factory: Optional[Callable[[str], Any]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if ticker_factory is None:
            import yfinance as yf

            ticker_factory = yf.Ticker
        self._ticker_factory = ticker_factory
        self._sleep = sleep_fn
        self._now = now_fn
        self._max_retries = max_retries

    def get_fundamentals(self, symbol: str) -> FundamentalsSnapshot:
        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                ticker = self._ticker_factory(symbol)
                return self._build_snapshot(symbol, ticker)
            except Exception as exc:  # noqa: BLE001 -- retried below, then re-raised typed
                last_error = exc
                if attempt < self._max_retries:
                    self._sleep(0.5 * (attempt + 1))
                    continue
        raise FundamentalsProviderError(
            f"Failed to fetch fundamentals for {symbol!r} after {self._max_retries + 1} attempts"
        ) from last_error

    def _build_snapshot(self, symbol: str, ticker: Any) -> FundamentalsSnapshot:
        info: dict = {}
        try:
            info = dict(getattr(ticker, "info", None) or {})
        except Exception:  # noqa: BLE001 -- `.info` itself can raise for some symbols; treat as absent
            info = {}

        quarterly_revenue = _extract_quarterly_series(ticker, "Total Revenue")
        quarterly_eps = _extract_quarterly_eps(ticker)

        return FundamentalsSnapshot(
            symbol=symbol,
            fetched_at=self._now(),
            provider="yfinance",
            trailing_pe=_safe_float(info.get("trailingPE")),
            forward_pe=_safe_float(info.get("forwardPE")),
            price_to_sales=_safe_float(info.get("priceToSalesTrailing12Months")),
            profit_margin=_safe_float(info.get("profitMargins")),
            return_on_equity=_safe_float(info.get("returnOnEquity")),
            debt_to_equity=_safe_float(info.get("debtToEquity")),
            free_cash_flow=_safe_float(info.get("freeCashflow")),
            quarterly_revenue=quarterly_revenue,
            quarterly_eps=quarterly_eps,
            market_cap=_safe_float(info.get("marketCap")),
        )


def _extract_quarterly_series(ticker: Any, row_label: str) -> list[float]:
    """Reads one row out of `ticker.quarterly_financials` (a pandas
    DataFrame: rows are line items, columns are quarter-end dates, most
    recent column first) and returns it OLDEST -> NEWEST, dropping any
    column that isn't a clean finite number rather than ever
    interpolating a gap."""
    try:
        frame = ticker.quarterly_financials
    except Exception:  # noqa: BLE001
        return []
    if frame is None or row_label not in getattr(frame, "index", []):
        return []
    try:
        row = frame.loc[row_label]
        columns_oldest_first = list(row.index)[::-1]
        values: list[float] = []
        for column in columns_oldest_first:
            parsed = _safe_float(row[column])
            if parsed is not None:
                values.append(parsed)
        return values
    except Exception:  # noqa: BLE001
        return []


def _extract_quarterly_eps(ticker: Any) -> list[float]:
    """yfinance exposes quarterly EPS via `ticker.quarterly_earnings`
    (older API, a DataFrame indexed by quarter label, oldest row first,
    with an "Earnings"/"EPS" column depending on version) OR via
    `ticker.get_earnings_dates()` in newer versions. Tries the simpler,
    long-stable `.quarterly_earnings` surface first; returns [] (never a
    guess) if neither shape is present -- callers treat that exactly like
    any other missing-data case."""
    try:
        frame = ticker.quarterly_earnings
    except Exception:  # noqa: BLE001
        frame = None
    if frame is None or not hasattr(frame, "columns"):
        return []
    eps_column = next((c for c in frame.columns if "eps" in str(c).lower()), None)
    if eps_column is None:
        return []
    try:
        values: list[float] = []
        for raw in frame[eps_column].tolist():
            parsed = _safe_float(raw)
            if parsed is not None:
                values.append(parsed)
        return values
    except Exception:  # noqa: BLE001
        return []
