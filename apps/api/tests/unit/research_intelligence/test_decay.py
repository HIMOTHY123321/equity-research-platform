from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.outcomes import evaluate_setup_outcome
from app.research.replay import run_replay
from app.research_intelligence.decay import _classify_pattern, signal_decay_profile
from app.research_intelligence.schemas import (
    BootstrapInterval,
    DecayHorizonStat,
    DecayPattern,
    DistributionSummary,
)
from app.schemas.market_data import Timeframe
from tests.unit.research.conftest import SYMBOL
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")
HORIZONS = (1, 3, 5, 10, 20)
_UNAVAILABLE_BOOTSTRAP = BootstrapInterval(available=False, statistic="median")


def _horizon_stat(horizon_bars: int, median: float, n: int = 30) -> DecayHorizonStat:
    return DecayHorizonStat(
        horizon_bars=horizon_bars,
        distribution=DistributionSummary(n=n, median=median, mean=median),
        bootstrap_interval=_UNAVAILABLE_BOOTSTRAP,
    )


def _config():
    from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG

    return DEFAULT_RESEARCH_INTELLIGENCE_CONFIG


def test_immediate_pattern_shows_up_fast_and_stays():
    stats = [
        _horizon_stat(1, 0.5),
        _horizon_stat(3, 0.48),
        _horizon_stat(5, 0.45),
        _horizon_stat(10, 0.40),
        _horizon_stat(20, 0.35),
    ]
    pattern, basis = _classify_pattern(stats, _config())
    assert pattern == DecayPattern.IMMEDIATE
    assert "earliest" in basis


def test_delayed_pattern_starts_small_and_grows():
    stats = [
        _horizon_stat(1, 0.05),
        _horizon_stat(3, 0.10),
        _horizon_stat(5, 0.20),
        _horizon_stat(10, 0.35),
        _horizon_stat(20, 0.50),
    ]
    pattern, _ = _classify_pattern(stats, _config())
    assert pattern == DecayPattern.DELAYED


def test_persistent_pattern_moderate_start_stays_strong():
    stats = [
        _horizon_stat(1, 0.20),
        _horizon_stat(3, 0.25),
        _horizon_stat(5, 0.35),
        _horizon_stat(10, 0.33),
        _horizon_stat(20, 0.32),
    ]
    pattern, _ = _classify_pattern(stats, _config())
    assert pattern == DecayPattern.PERSISTENT


def test_decaying_pattern_peaks_early_then_fades_away():
    # earliest == peak, but by the last horizon it's faded to 4% of peak --
    # must NOT be misread as "immediate" just because it started strong.
    stats = [
        _horizon_stat(1, 0.5),
        _horizon_stat(3, 0.3),
        _horizon_stat(5, 0.15),
        _horizon_stat(10, 0.05),
        _horizon_stat(20, 0.02),
    ]
    pattern, basis = _classify_pattern(stats, _config())
    assert pattern == DecayPattern.DECAYING
    assert "faded" in basis


def test_decaying_pattern_via_sign_reversal():
    stats = [_horizon_stat(1, 0.3), _horizon_stat(3, 0.1), _horizon_stat(5, -0.2), _horizon_stat(10, -0.3)]
    pattern, basis = _classify_pattern(stats, _config())
    assert pattern == DecayPattern.DECAYING
    assert "reverses" in basis


def test_inconclusive_with_fewer_than_two_usable_horizons():
    stats = [_horizon_stat(1, 0.5, n=5)]  # below small_sample_min
    pattern, _ = _classify_pattern(stats, _config())
    assert pattern == DecayPattern.INCONCLUSIVE


def test_inconclusive_when_every_median_is_zero():
    stats = [_horizon_stat(1, 0.0), _horizon_stat(5, 0.0), _horizon_stat(20, 0.0)]
    pattern, _ = _classify_pattern(stats, _config())
    assert pattern == DecayPattern.INCONCLUSIVE


def test_small_sample_horizons_are_excluded_not_zeroed():
    # Horizon 1 has an insufficient sample and a wild median -- it must be
    # dropped from classification entirely, not treated as if median=0.
    stats = [
        _horizon_stat(1, 999.0, n=3),
        _horizon_stat(3, 0.5),
        _horizon_stat(5, 0.48),
        _horizon_stat(10, 0.40),
        _horizon_stat(20, 0.35),
    ]
    pattern, basis = _classify_pattern(stats, _config())
    assert pattern == DecayPattern.IMMEDIATE
    assert "999" not in basis


def test_signal_decay_profile_produces_one_stat_per_horizon_on_real_data():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "decay-test")
    entries = []
    for e in result.ledger_entries:
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)

    qualified = [e for e in entries if e.detection.current_state == "qualified"]
    profile = signal_decay_profile(qualified, HORIZONS, seed=1)
    assert [h.horizon_bars for h in profile.horizons] == list(HORIZONS)
    assert profile.pattern in DecayPattern
    assert profile.pattern_basis


def test_signal_decay_profile_flags_small_sample_horizons():
    start, end = SPY_1H[0].timestamp, SPY_1H[-1].timestamp
    result = run_replay(SYMBOL, Timeframe.ONE_HOUR, start, end, SPY_1H, SPY_1D, SPY_1H, "decay-warn-test")
    entries = []
    for e in result.ledger_entries:
        outcome = evaluate_setup_outcome(e.detection, SPY_1H, DEFAULT_RESEARCH_CONFIG)
        entries.append(e.model_copy(update={"outcome": outcome}) if outcome else e)

    trend_pullbacks = [e for e in entries if e.setup_type == "trend_pullback"]
    profile = signal_decay_profile(trend_pullbacks, HORIZONS, seed=2)
    # The real fixture has well under 20 trend_pullback entries -- every
    # horizon should carry a small/insufficient-sample warning.
    assert all(h.warnings for h in profile.horizons)
