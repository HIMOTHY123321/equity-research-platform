"""Phase 11 (#A closing requirement): "the same historical as_of must
produce the same EvidencePacket even if future candles/news are appended."
Three independent proofs, one per section that has its own as_of-bounding
mechanism:

1. Market data (structure/features/support-resistance/setup) -- truncate_to
   _as_of (app.market_structure.common et al.) already does this for every
   existing live route; here it's proven for build_evidence_packet's own
   as_of parameter.
2. News/catalyst context -- app.ai_analysis.evidence_packet
   ._catalyst_context_and_event's own as_of-bounded fetch (#E discipline,
   same as app.news.provider's contract).
3. Historical research -- only research runs whose own `end_date <= as_of`
   are ever pooled (app.ai_analysis.evidence_packet._matching_run_ids).
"""

from __future__ import annotations

from datetime import timedelta

from app.ai_analysis.evidence_packet import build_evidence_packet
from app.market_data.provider import MarketDataProvider
from app.news.fixture_provider import FixtureNewsProvider
from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.engine import execute_research_run
from app.schemas.market_data import Timeframe
from tests.unit.ai_analysis.conftest import SPY_1D, SPY_1H, make_repositories, make_session
from tests.unit.news.conftest import raw_article

_ANCHOR_INDEX = len(SPY_1H) // 2
_AS_OF = SPY_1H[_ANCHOR_INDEX].timestamp


class _TruncatedProvider(MarketDataProvider):
    """Returns only candles up to (and including) a fixed cutoff -- models
    "the world as it was" at that instant, independent of `as_of` passed
    into the engines, so a determinism test can prove the engines' own
    truncation (not merely the fixture's own limited data) is what's doing
    the work."""

    def __init__(self, cutoff) -> None:
        self._cutoff = cutoff

    def _bounded(self, series):
        return [c for c in series if c.timestamp <= self._cutoff]

    def get_candles(self, symbol, timeframe, limit=200):
        series = {
            (Timeframe.ONE_HOUR): SPY_1H,
            (Timeframe.ONE_DAY): SPY_1D,
            (Timeframe.FOUR_HOUR): SPY_1H,
        }.get(timeframe, [])
        return self._bounded(series)[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def _build_packet(market_provider, news_provider, research_repository, news_repository):
    return build_evidence_packet(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        market_provider=market_provider,
        news_provider=news_provider,
        news_repository=news_repository,
        research_repository=research_repository,
        as_of=_AS_OF,
    )


def test_future_candles_do_not_change_structure_features_or_levels():
    session = make_session()
    research_repository, news_repository = make_repositories(session)

    provider_without_future = _TruncatedProvider(_AS_OF)
    provider_with_future = _TruncatedProvider(SPY_1H[-1].timestamp)  # every candle, including future ones

    empty_news = FixtureNewsProvider([])
    packet_a = _build_packet(provider_without_future, empty_news, research_repository, news_repository)
    packet_b = _build_packet(provider_with_future, empty_news, research_repository, news_repository)

    # `data_quality` is deliberately excluded: it honestly reports how many
    # future candles each provider handed over and how many were dropped
    # (different by construction here), which is the truncation working
    # correctly, not a lookahead leak. The actual analysis fields --
    # everything else -- must be identical regardless.
    assert packet_a.structure.model_dump(exclude={"data_quality"}) == packet_b.structure.model_dump(
        exclude={"data_quality"}
    )
    assert packet_a.features.model_dump(exclude={"data_quality"}) == packet_b.features.model_dump(
        exclude={"data_quality"}
    )
    assert packet_a.support_resistance.model_dump(
        exclude={"data_quality"}
    ) == packet_b.support_resistance.model_dump(exclude={"data_quality"})
    assert packet_a.current_price == packet_b.current_price
    assert packet_a.packet_id == packet_b.packet_id


def test_future_news_article_does_not_change_catalyst_context():
    session = make_session()
    research_repository, news_repository_a = make_repositories(session)
    _, news_repository_b = make_repositories(make_session())

    past_article = raw_article(
        "Acme reports quarterly earnings beat", _AS_OF - timedelta(hours=2), ["SPY"], source="Reuters"
    )
    future_article = raw_article(
        "Acme announces surprise product recall", _AS_OF + timedelta(hours=2), ["SPY"], source="Reuters"
    )

    provider = _TruncatedProvider(SPY_1H[-1].timestamp)

    packet_before = _build_packet(
        provider, FixtureNewsProvider([past_article]), research_repository, news_repository_a
    )
    packet_after = _build_packet(
        provider, FixtureNewsProvider([past_article, future_article]), research_repository, news_repository_b
    )

    # Symbol-level packets (no setup_id) have no SetupCatalystContext -- that
    # concept requires a setup to anchor to -- but they do still surface the
    # most recent catalyst event as of `as_of`, which is what this proof
    # targets.
    assert packet_before.nearest_catalyst_event is not None
    assert packet_after.nearest_catalyst_event is not None
    assert packet_before.nearest_catalyst_event.event_id == packet_after.nearest_catalyst_event.event_id
    # The future article must never surface as the nearest/only catalyst.
    assert "recall" not in packet_after.nearest_catalyst_event.title


def _run_replay(repository, start, end):
    # Full fixture history is passed as context (matching how
    # /api/research/universe-replay always fetches the whole requested
    # range up front) -- `start`/`end` alone bound which candles the replay
    # actually produces ledger entries for and, more importantly here, what
    # `run.end_date` ends up as.
    return execute_research_run(
        symbol="SPY",
        timeframe=Timeframe.ONE_HOUR,
        start_date=start,
        end_date=end,
        primary_candles=SPY_1H,
        daily_candles=SPY_1D,
        four_hour_candles=SPY_1H,
        provider_name="fixture",
        repository=repository,
        research_config=DEFAULT_RESEARCH_CONFIG,
    )


def test_a_research_run_ending_after_as_of_is_never_pooled():
    session = make_session()
    research_repository, news_repository = make_repositories(session)

    past_run_id = _run_replay(research_repository, SPY_1H[0].timestamp, _AS_OF)
    provider = _TruncatedProvider(SPY_1H[-1].timestamp)

    packet_before = _build_packet(provider, FixtureNewsProvider([]), research_repository, news_repository)
    run_ids_before = set(packet_before.provenance.research_run_ids)
    assert past_run_id in run_ids_before

    # A second run whose replay window extends past `_AS_OF` -- must never
    # be pooled into a packet built at `_AS_OF`, even though it now exists
    # in the same repository.
    future_run_id = _run_replay(research_repository, SPY_1H[0].timestamp, SPY_1H[-1].timestamp)

    packet_after = _build_packet(provider, FixtureNewsProvider([]), research_repository, news_repository)
    run_ids_after = set(packet_after.provenance.research_run_ids)

    assert future_run_id not in run_ids_after
    assert run_ids_after == run_ids_before
