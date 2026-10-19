"""Deterministic factor computation -- turns a FundamentalsSnapshot plus
a daily candle series into one LongTermFactorBundle. Every function here
is a PURE function of its inputs: no network calls, no randomness, no
hidden/mutable state, and no reliance on wall-clock time except the
caller-supplied `as_of` -- the same inputs always produce the same
factor states (required for app.long_term_research.service's determinism
guarantee).

Anti-lookahead: every candle with `timestamp > as_of` is defensively
dropped before any computation runs, even though callers (see
app.long_term_research.service) are already responsible for only ever
fetching candles up to `as_of` -- belt-and-suspenders, matching this
codebase's existing "append-future invariant" discipline
(app.ai_analysis's point-in-time pipeline).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.features.indicators import sma
from app.long_term_research.schemas import (
    BusinessQualityState,
    EarningsTrendState,
    FundamentalsSnapshot,
    GrowthState,
    LongTermFactorBundle,
    LongTermFactorEvidence,
    LongTermTrendState,
    ValuationState,
)
from app.schemas.market_data import Candle

LIMITED_HISTORY_DAYS_THRESHOLD = 380
"""Roughly one calendar year plus a buffer -- below this, a symbol is
labeled LIMITED HISTORY per spec (e.g. a recent IPO/SPAC like SPCX),
rather than silently computing long-term-trend/valuation-vs-own-history
factors as if years of data existed."""

MIN_DAILY_CANDLES_FOR_TREND = 60
MIN_QUARTERS_FOR_EARNINGS_TREND = 3
MIN_QUARTERS_FOR_GROWTH = 5
MIN_QUARTERS_FOR_OWN_HISTORY_VALUATION = 8


def _bounded_candles(candles: list[Candle], as_of: datetime) -> list[Candle]:
    bounded = [c for c in candles if c.timestamp <= as_of]
    return sorted(bounded, key=lambda c: c.timestamp)


def compute_business_quality(
    fundamentals: FundamentalsSnapshot,
) -> tuple[BusinessQualityState, LongTermFactorEvidence]:
    evidence = LongTermFactorEvidence()
    signals: list[int] = []

    if fundamentals.profit_margin is not None:
        if fundamentals.profit_margin >= 0.10:
            signals.append(1)
            evidence.positive.append(f"Profit margin is healthy at {fundamentals.profit_margin:.1%}.")
        elif fundamentals.profit_margin < 0:
            signals.append(-1)
            evidence.negative.append(f"Profit margin is negative ({fundamentals.profit_margin:.1%}).")
        else:
            signals.append(0)
    else:
        evidence.missing.append("profit margin")

    if fundamentals.return_on_equity is not None:
        if fundamentals.return_on_equity >= 0.12:
            signals.append(1)
            evidence.positive.append(f"Return on equity is strong at {fundamentals.return_on_equity:.1%}.")
        elif fundamentals.return_on_equity < 0:
            signals.append(-1)
            evidence.negative.append(f"Return on equity is negative ({fundamentals.return_on_equity:.1%}).")
        else:
            signals.append(0)
    else:
        evidence.missing.append("return on equity")

    if fundamentals.debt_to_equity is not None:
        if fundamentals.debt_to_equity > 200:
            signals.append(-1)
            evidence.negative.append(f"Debt-to-equity is elevated at {fundamentals.debt_to_equity:.0f}.")
        elif fundamentals.debt_to_equity < 100:
            signals.append(1)
            evidence.positive.append(f"Debt-to-equity is conservative at {fundamentals.debt_to_equity:.0f}.")
        else:
            signals.append(0)
    else:
        evidence.missing.append("debt-to-equity")

    if fundamentals.free_cash_flow is not None:
        if fundamentals.free_cash_flow > 0:
            signals.append(1)
            evidence.positive.append("Free cash flow is positive.")
        else:
            signals.append(-1)
            evidence.negative.append("Free cash flow is negative.")
    else:
        evidence.missing.append("free cash flow")

    if not signals:
        return BusinessQualityState.NOT_ENOUGH_EVIDENCE, evidence

    net = sum(signals)
    if net >= 2 and all(s >= 0 for s in signals):
        return BusinessQualityState.STRONG, evidence
    if net < 0:
        return BusinessQualityState.WEAK, evidence
    return BusinessQualityState.STABLE, evidence


def compute_earnings_trend(
    fundamentals: FundamentalsSnapshot,
) -> tuple[EarningsTrendState, LongTermFactorEvidence]:
    evidence = LongTermFactorEvidence()
    eps = fundamentals.quarterly_eps
    if len(eps) < MIN_QUARTERS_FOR_EARNINGS_TREND:
        evidence.missing.append(
            f"quarterly EPS history (have {len(eps)}, need at least {MIN_QUARTERS_FOR_EARNINGS_TREND})"
        )
        return EarningsTrendState.NOT_ENOUGH_EVIDENCE, evidence

    recent = eps[-4:] if len(eps) >= 4 else eps
    deltas = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
    increasing = sum(1 for d in deltas if d > 0)
    decreasing = sum(1 for d in deltas if d < 0)

    if increasing > decreasing:
        evidence.positive.append(
            f"Quarterly EPS has risen in {increasing} of the last {len(deltas)} reported "
            "quarter-over-quarter periods."
        )
        return EarningsTrendState.IMPROVING, evidence
    if decreasing > increasing:
        evidence.negative.append(
            f"Quarterly EPS has fallen in {decreasing} of the last {len(deltas)} reported "
            "quarter-over-quarter periods."
        )
        return EarningsTrendState.WEAKENING, evidence
    return EarningsTrendState.STABLE, evidence


def compute_growth(
    fundamentals: FundamentalsSnapshot,
) -> tuple[GrowthState, LongTermFactorEvidence]:
    evidence = LongTermFactorEvidence()
    revenue = fundamentals.quarterly_revenue
    eps = fundamentals.quarterly_eps

    revenue_yoy: Optional[float] = None
    if len(revenue) >= MIN_QUARTERS_FOR_GROWTH and revenue[-5] != 0:
        revenue_yoy = (revenue[-1] - revenue[-5]) / abs(revenue[-5])
    eps_yoy: Optional[float] = None
    if len(eps) >= MIN_QUARTERS_FOR_GROWTH and eps[-5] != 0:
        eps_yoy = (eps[-1] - eps[-5]) / abs(eps[-5])

    if revenue_yoy is None and eps_yoy is None:
        evidence.missing.append(
            f"at least {MIN_QUARTERS_FOR_GROWTH} quarters of revenue/EPS history for a year-over-year "
            "growth comparison"
        )
        return GrowthState.NOT_ENOUGH_EVIDENCE, evidence

    available = [v for v in (revenue_yoy, eps_yoy) if v is not None]
    if revenue_yoy is not None:
        evidence.positive.append(f"Revenue grew {revenue_yoy:.1%} year-over-year.") if revenue_yoy > 0 else (
            evidence.negative.append(f"Revenue declined {abs(revenue_yoy):.1%} year-over-year.")
        )
    if eps_yoy is not None:
        evidence.positive.append(f"EPS grew {eps_yoy:.1%} year-over-year.") if eps_yoy > 0 else (
            evidence.negative.append(f"EPS declined {abs(eps_yoy):.1%} year-over-year.")
        )

    if all(v >= 0.10 for v in available):
        return GrowthState.STRONG, evidence
    if all(v < 0 for v in available):
        return GrowthState.WEAK, evidence
    return GrowthState.MODERATE, evidence


def compute_valuation(
    fundamentals: FundamentalsSnapshot, candles: list[Candle], as_of: datetime
) -> tuple[ValuationState, LongTermFactorEvidence]:
    evidence = LongTermFactorEvidence()
    bounded = _bounded_candles(candles, as_of)
    eps = fundamentals.quarterly_eps

    # Tier 1 (preferred): price-implied P/E now vs. this SAME company's
    # own P/E roughly one year ago -- a genuine "relative to own
    # available history" comparison, not an absolute band.
    if len(eps) >= MIN_QUARTERS_FOR_OWN_HISTORY_VALUATION and len(bounded) >= 252:
        ttm_eps_now = sum(eps[-4:])
        ttm_eps_year_ago = sum(eps[-8:-4])
        price_now = bounded[-1].close
        one_year_ago_target = bounded[-1].timestamp - timedelta(days=365)
        price_year_ago = min(bounded, key=lambda c: abs((c.timestamp - one_year_ago_target).days)).close

        if ttm_eps_now > 0 and ttm_eps_year_ago > 0:
            pe_now = price_now / ttm_eps_now
            pe_year_ago = price_year_ago / ttm_eps_year_ago
            if pe_now < pe_year_ago * 0.85:
                evidence.positive.append(
                    f"Trailing P/E of {pe_now:.1f} is below this stock's own P/E of {pe_year_ago:.1f} "
                    "a year ago."
                )
                return ValuationState.CHEAP, evidence
            if pe_now > pe_year_ago * 1.15:
                evidence.negative.append(
                    f"Trailing P/E of {pe_now:.1f} is above this stock's own P/E of {pe_year_ago:.1f} "
                    "a year ago."
                )
                return ValuationState.EXPENSIVE, evidence
            evidence.positive.append(
                f"Trailing P/E of {pe_now:.1f} is in line with this stock's own P/E of {pe_year_ago:.1f} "
                "a year ago."
            )
            return ValuationState.REASONABLE, evidence

    # Tier 2 (fallback, disclosed limitation): fixed absolute bands when
    # a genuine own-history comparison isn't available.
    if fundamentals.trailing_pe is not None and fundamentals.trailing_pe > 0:
        pe = fundamentals.trailing_pe
        if pe < 15:
            evidence.positive.append(f"Trailing P/E of {pe:.1f} is low on an absolute basis.")
            return ValuationState.CHEAP, evidence
        if pe > 25:
            evidence.negative.append(f"Trailing P/E of {pe:.1f} is high on an absolute basis.")
            return ValuationState.EXPENSIVE, evidence
        evidence.positive.append(f"Trailing P/E of {pe:.1f} is within a typical range.")
        return ValuationState.REASONABLE, evidence
    if fundamentals.price_to_sales is not None and fundamentals.price_to_sales > 0:
        ps = fundamentals.price_to_sales
        if ps < 2:
            evidence.positive.append(f"Price-to-sales of {ps:.1f} is low on an absolute basis.")
            return ValuationState.CHEAP, evidence
        if ps > 6:
            evidence.negative.append(f"Price-to-sales of {ps:.1f} is high on an absolute basis.")
            return ValuationState.EXPENSIVE, evidence
        evidence.positive.append(f"Price-to-sales of {ps:.1f} is within a typical range.")
        return ValuationState.REASONABLE, evidence

    evidence.missing.append(
        "a usable trailing P/E, price-to-sales, or enough EPS/price history to compare against this "
        "stock's own past valuation"
    )
    return ValuationState.NOT_ENOUGH_EVIDENCE, evidence


def compute_long_term_trend(
    candles: list[Candle], as_of: datetime
) -> tuple[LongTermTrendState, LongTermFactorEvidence, Optional[float], Optional[float], Optional[float]]:
    """Returns (state, evidence, accumulation_area_low,
    accumulation_area_high, invalidation_level)."""
    evidence = LongTermFactorEvidence()
    bounded = _bounded_candles(candles, as_of)

    if len(bounded) < MIN_DAILY_CANDLES_FOR_TREND:
        evidence.missing.append(
            f"at least {MIN_DAILY_CANDLES_FOR_TREND} daily candles of price history (have {len(bounded)})"
        )
        return LongTermTrendState.NOT_ENOUGH_EVIDENCE, evidence, None, None, None

    closes = [c.close for c in bounded]
    current_price = closes[-1]
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)
    window_for_high = closes[-252:] if len(closes) >= 252 else closes
    fifty_two_week_high = max(window_for_high)
    drawdown = (fifty_two_week_high - current_price) / fifty_two_week_high if fifty_two_week_high > 0 else 0.0

    recent_window = bounded[-10:]
    accumulation_area_low = min(c.low for c in recent_window)
    accumulation_area_high = round(accumulation_area_low * 1.02, 2)
    invalidation_level = round(accumulation_area_low * 0.95, 2)

    if sma200 is not None:
        if current_price > sma50 > sma200 and drawdown < 0.20:
            evidence.positive.append(
                f"Price (${current_price:.2f}) is above both its 50-day and 200-day averages, "
                f"{drawdown:.0%} off its 52-week high."
            )
            state = LongTermTrendState.CONSTRUCTIVE
        elif current_price < sma50 < sma200 or drawdown > 0.35:
            evidence.negative.append(
                f"Price (${current_price:.2f}) is below its long-term averages and/or {drawdown:.0%} off "
                "its 52-week high."
            )
            state = LongTermTrendState.WEAKENING
        else:
            state = LongTermTrendState.NEUTRAL
    else:
        # Fewer than 200 daily candles -- a looser, shorter-horizon
        # fallback (contributes to limited_history being True upstream).
        if current_price > sma50 and drawdown < 0.15:
            evidence.positive.append(
                f"Price (${current_price:.2f}) is above its 50-day average, {drawdown:.0%} off its "
                "recent high, though full long-term history is not yet available."
            )
            state = LongTermTrendState.CONSTRUCTIVE
        elif current_price < sma50 and drawdown > 0.30:
            evidence.negative.append(
                f"Price (${current_price:.2f}) is below its 50-day average and {drawdown:.0%} off its "
                "recent high, though full long-term history is not yet available."
            )
            state = LongTermTrendState.WEAKENING
        else:
            state = LongTermTrendState.NEUTRAL

    return state, evidence, accumulation_area_low, accumulation_area_high, invalidation_level


def build_factor_bundle(
    fundamentals: FundamentalsSnapshot, candles: list[Candle], as_of: datetime
) -> LongTermFactorBundle:
    bounded = _bounded_candles(candles, as_of)
    history_days = (as_of.date() - bounded[0].timestamp.date()).days if bounded else 0
    limited_history = history_days < LIMITED_HISTORY_DAYS_THRESHOLD

    business_quality, business_quality_evidence = compute_business_quality(fundamentals)
    earnings_trend, earnings_trend_evidence = compute_earnings_trend(fundamentals)
    valuation, valuation_evidence = compute_valuation(fundamentals, candles, as_of)
    growth, growth_evidence = compute_growth(fundamentals)
    (
        long_term_trend,
        long_term_trend_evidence,
        accumulation_area_low,
        accumulation_area_high,
        invalidation_level,
    ) = compute_long_term_trend(candles, as_of)

    return LongTermFactorBundle(
        business_quality=business_quality,
        business_quality_evidence=business_quality_evidence,
        earnings_trend=earnings_trend,
        earnings_trend_evidence=earnings_trend_evidence,
        valuation=valuation,
        valuation_evidence=valuation_evidence,
        growth=growth,
        growth_evidence=growth_evidence,
        long_term_trend=long_term_trend,
        long_term_trend_evidence=long_term_trend_evidence,
        history_days=history_days,
        limited_history=limited_history,
        accumulation_area_low=accumulation_area_low,
        accumulation_area_high=accumulation_area_high,
        invalidation_level=invalidation_level,
    )
