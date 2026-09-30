"""Phase 19.1: TwelveDataStreamingProvider's wire-protocol handling and,
critically, its `entitlement_hint()` -- the ONLY place genuine per-symbol
Twelve Data entitlement evidence is produced. `ws_connect` is injected as a
fake so this suite never opens a real socket or needs a real account.
"""

from __future__ import annotations

import json

import pytest

from app.live.entitlement import EntitlementStatus
from app.live.streaming import CHANNEL_TRADES, StreamStatus, StreamTrade
from app.market_data.exceptions import AuthenticationError, RateLimitError
from app.market_data.twelve_data_streaming import TwelveDataStreamingProvider


class _FakeWebSocket:
    def __init__(self, incoming: list):
        self.sent: list[str] = []
        self._incoming = list(incoming)
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


def _connect_factory(ws: _FakeWebSocket, raise_on_connect: Exception | None = None):
    async def _connect(url):
        if raise_on_connect is not None:
            raise raise_on_connect
        return ws

    return _connect


@pytest.mark.asyncio
async def test_connect_builds_url_with_apikey_and_never_logs_it(caplog):
    ws = _FakeWebSocket(incoming=[])
    provider = TwelveDataStreamingProvider("super-secret-key", ws_connect=_connect_factory(ws))
    await provider.connect()
    assert "super-secret-key" not in caplog.text


@pytest.mark.asyncio
async def test_connect_failure_raises_authentication_error_never_leaking_the_key():
    provider = TwelveDataStreamingProvider(
        "bad-key", ws_connect=_connect_factory(None, raise_on_connect=ConnectionRefusedError("401"))
    )
    with pytest.raises(AuthenticationError) as excinfo:
        await provider.connect()
    assert "bad-key" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_subscribe_sends_symbols_param():
    ws = _FakeWebSocket(incoming=[])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    await provider.subscribe("AAPL", frozenset({CHANNEL_TRADES}))

    sent = json.loads(ws.sent[0])
    assert sent == {"action": "subscribe", "params": {"symbols": "AAPL"}}


@pytest.mark.asyncio
async def test_unsubscribe_sends_unsubscribe_and_clears_local_entitlement_state():
    ws = _FakeWebSocket(incoming=[])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()
    provider.subscribed_symbols.add("AAPL")

    await provider.unsubscribe("AAPL", frozenset({CHANNEL_TRADES}))

    sent = json.loads(ws.sent[-1])
    assert sent == {"action": "unsubscribe", "params": {"symbols": "AAPL"}}
    assert "AAPL" not in provider.subscribed_symbols


@pytest.mark.asyncio
async def test_heartbeat_is_skipped_not_yielded():
    ws = _FakeWebSocket(incoming=[json.dumps({"event": "heartbeat"})])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert events == []


@pytest.mark.asyncio
async def test_price_event_maps_to_stream_trade_with_no_fabricated_size():
    message = {"event": "price", "symbol": "AAPL", "price": 123.45, "timestamp": 1755440400}
    ws = _FakeWebSocket(incoming=[json.dumps(message)])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert len(events) == 1
    assert isinstance(events[0], StreamTrade)
    assert events[0].price == 123.45
    assert events[0].size == 0.0


@pytest.mark.asyncio
async def test_successful_subscribe_status_upgrades_entitlement_to_trial_only():
    message = {
        "event": "subscribe-status",
        "status": "ok",
        "success": [{"symbol": "AAPL"}],
        "fails": [],
    }
    ws = _FakeWebSocket(incoming=[json.dumps(message)])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert isinstance(events[0], StreamStatus)
    assert "AAPL" in provider.subscribed_symbols

    hint = provider.entitlement_hint()
    assert hint is not None
    assert hint.status == EntitlementStatus.TRIAL_ONLY
    assert hint.confirmed is True


@pytest.mark.asyncio
async def test_rejected_subscription_never_reports_confirmed_entitlement():
    message = {
        "event": "subscribe-status",
        "status": "ok",
        "success": [],
        "fails": [{"symbol": "ZZZZZ"}],
    }
    ws = _FakeWebSocket(incoming=[json.dumps(message)])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    _ = [event async for event in provider.events()]
    assert "ZZZZZ" in provider.rejected_symbols

    hint = provider.entitlement_hint()
    assert hint is not None
    assert hint.status == EntitlementStatus.NOT_ENTITLED
    assert hint.confirmed is False


@pytest.mark.asyncio
async def test_a_price_tick_alone_is_sufficient_evidence_of_entitlement():
    """Even without ever seeing an explicit subscribe-status ack, a genuine
    price tick for a symbol is itself proof that symbol streams live."""
    message = {"event": "price", "symbol": "AAPL", "price": 1.0, "timestamp": 1755440400}
    ws = _FakeWebSocket(incoming=[json.dumps(message)])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()
    _ = [event async for event in provider.events()]

    hint = provider.entitlement_hint()
    assert hint is not None
    assert hint.status == EntitlementStatus.TRIAL_ONLY


@pytest.mark.asyncio
async def test_no_evidence_yet_yields_no_entitlement_hint():
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(_FakeWebSocket([])))
    await provider.connect()
    assert provider.entitlement_hint() is None


@pytest.mark.asyncio
async def test_rate_limit_error_event_raises_rate_limit_error_and_sets_hint():
    message = {"status": "error", "code": 429, "message": "quota exceeded"}
    ws = _FakeWebSocket(incoming=[json.dumps(message)])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    with pytest.raises(RateLimitError):
        async for _event in provider.events():
            pass

    hint = provider.entitlement_hint()
    assert hint is not None
    assert hint.status == EntitlementStatus.RATE_LIMITED
    assert hint.confirmed is False


@pytest.mark.asyncio
async def test_auth_error_event_raises_authentication_error_and_sets_misconfigured_hint():
    message = {"status": "error", "code": 401, "message": "invalid apikey"}
    ws = _FakeWebSocket(incoming=[json.dumps(message)])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    with pytest.raises(AuthenticationError):
        async for _event in provider.events():
            pass

    hint = provider.entitlement_hint()
    assert hint is not None
    assert hint.status == EntitlementStatus.MISCONFIGURED


@pytest.mark.asyncio
async def test_malformed_price_event_is_dropped_not_raised():
    # missing price/timestamp
    ws = _FakeWebSocket(incoming=[json.dumps({"event": "price", "symbol": "AAPL"})])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert events == []


@pytest.mark.asyncio
async def test_malformed_json_is_dropped_not_raised():
    ws = _FakeWebSocket(incoming=["not valid json{{{"])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert events == []


@pytest.mark.asyncio
async def test_oversized_message_is_dropped():
    huge = json.dumps(
        {"event": "price", "symbol": "AAPL", "price": 1, "timestamp": 1, "padding": "x" * 2_000_000}
    )
    ws = _FakeWebSocket(incoming=[huge])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert events == []


@pytest.mark.asyncio
async def test_disconnect_closes_the_socket():
    ws = _FakeWebSocket(incoming=[])
    provider = TwelveDataStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()
    await provider.disconnect()
    assert ws.closed is True
