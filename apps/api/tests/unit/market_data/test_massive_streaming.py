"""Phase 12.2 (#B/#V/#Y): MassiveStreamingProvider's wire-protocol handling
-- auth handshake, channel-string subscribe/unsubscribe, message
normalization, and malformed/oversized-message rejection. `ws_connect` is
injected as a fake so this suite never opens a real socket or needs a real
Massive account.
"""

from __future__ import annotations

import json

import pytest

from app.live.streaming import (
    CHANNEL_AGGREGATES,
    CHANNEL_QUOTES,
    CHANNEL_TRADES,
    StreamAggregate,
    StreamNbbo,
    StreamStatus,
    StreamTrade,
)
from app.market_data.exceptions import AuthenticationError
from app.market_data.massive_streaming import MassiveStreamingProvider


class _FakeWebSocket:
    def __init__(self, incoming: list, auto_ack_auth: bool = True):
        self.sent: list[str] = []
        self._incoming = list(incoming)
        self._auto_ack_auth = auto_ack_auth
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)
        payload = json.loads(message)
        if self._auto_ack_auth and payload.get("action") == "auth":
            self._incoming.insert(0, json.dumps([{"ev": "status", "status": "auth_success"}]))

    async def recv(self) -> str:
        if not self._incoming:
            raise ConnectionError("no more fake messages")
        return self._incoming.pop(0)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


def _connect_factory(ws: _FakeWebSocket):
    async def _connect(url):
        return ws

    return _connect


@pytest.mark.asyncio
async def test_connect_sends_auth_and_succeeds_on_auth_success():
    ws = _FakeWebSocket(incoming=[])
    provider = MassiveStreamingProvider("secret-key", ws_connect=_connect_factory(ws))
    await provider.connect()

    sent = json.loads(ws.sent[0])
    assert sent == {"action": "auth", "params": "secret-key"}


@pytest.mark.asyncio
async def test_connect_raises_authentication_error_on_rejection():
    incoming = [json.dumps([{"ev": "status", "status": "auth_failed"}])]
    ws = _FakeWebSocket(incoming=incoming, auto_ack_auth=False)
    provider = MassiveStreamingProvider("bad-key", ws_connect=_connect_factory(ws))
    with pytest.raises(AuthenticationError):
        await provider.connect()


@pytest.mark.asyncio
async def test_subscribe_builds_the_correct_channel_prefixed_params():
    ws = _FakeWebSocket(incoming=[])
    provider = MassiveStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()
    ws.sent.clear()

    await provider.subscribe("AAPL", frozenset({CHANNEL_TRADES, CHANNEL_QUOTES, CHANNEL_AGGREGATES}))

    sent = json.loads(ws.sent[0])
    assert sent["action"] == "subscribe"
    params = set(sent["params"].split(","))
    assert params == {"T.AAPL", "Q.AAPL", "A.AAPL"}


@pytest.mark.asyncio
async def test_unsubscribe_sends_the_unsubscribe_action():
    ws = _FakeWebSocket(incoming=[])
    provider = MassiveStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()
    await provider.subscribe("AAPL", frozenset({CHANNEL_TRADES}))
    ws.sent.clear()

    await provider.unsubscribe("AAPL", frozenset({CHANNEL_TRADES}))

    sent = json.loads(ws.sent[0])
    assert sent == {"action": "unsubscribe", "params": "T.AAPL"}


@pytest.mark.asyncio
async def test_events_normalizes_trade_quote_aggregate_and_status():
    trade = {
        "ev": "T",
        "sym": "AAPL",
        "p": 114.125,
        "s": 100,
        "x": 4,
        "c": [0, 12],
        "t": 1536036818784,
        "q": 5,
    }
    quote = {"ev": "Q", "sym": "AAPL", "bp": 114.1, "bs": 1, "ap": 114.2, "as": 1, "t": 1536036818900, "q": 6}
    agg = {
        "ev": "A",
        "sym": "AAPL",
        "o": 114.0,
        "h": 114.3,
        "l": 113.9,
        "c": 114.2,
        "v": 500,
        "s": 1536036818000,
        "e": 1536036819000,
    }
    status = {"ev": "status", "status": "connected"}
    messages = [json.dumps([trade, quote, agg, status])]
    ws = _FakeWebSocket(incoming=messages)
    provider = MassiveStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]

    assert isinstance(events[0], StreamTrade)
    assert events[0].price == 114.125
    assert events[0].sequence == 5
    assert isinstance(events[1], StreamNbbo)
    assert events[1].bid == 114.1
    assert isinstance(events[2], StreamAggregate)
    assert events[2].volume == 500
    assert isinstance(events[3], StreamStatus)


@pytest.mark.asyncio
async def test_malformed_json_is_dropped_not_raised():
    ws = _FakeWebSocket(incoming=["not valid json{{{"])
    provider = MassiveStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert events == []


@pytest.mark.asyncio
async def test_message_missing_required_fields_is_dropped_not_raised():
    ws = _FakeWebSocket(incoming=[json.dumps([{"ev": "T", "sym": "AAPL"}])])  # missing p/s/t
    provider = MassiveStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert events == []


@pytest.mark.asyncio
async def test_unknown_event_type_is_ignored():
    ws = _FakeWebSocket(incoming=[json.dumps([{"ev": "LULD", "sym": "AAPL"}])])
    provider = MassiveStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert events == []


@pytest.mark.asyncio
async def test_oversized_message_is_dropped():
    huge = json.dumps([{"ev": "T", "sym": "AAPL", "p": 1, "s": 1, "t": 1, "padding": "x" * 2_000_000}])
    ws = _FakeWebSocket(incoming=[huge])
    provider = MassiveStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()

    events = [event async for event in provider.events()]
    assert events == []


@pytest.mark.asyncio
async def test_disconnect_closes_the_socket():
    ws = _FakeWebSocket(incoming=[])
    provider = MassiveStreamingProvider("key", ws_connect=_connect_factory(ws))
    await provider.connect()
    await provider.disconnect()
    assert ws.closed is True
