"""Phase 20: app.notifications.pushover in isolation -- every HTTP
interaction goes through an injected httpx.MockTransport, so these tests
never touch the real network and never need a real Pushover account."""

from __future__ import annotations

import httpx
import pytest

from app.notifications.pushover import PushoverMessage, PushoverProvider


def _provider(handler, **kwargs) -> PushoverProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PushoverProvider(
        "test-app-token", "test-user-key", client=client, sleep_fn=lambda _seconds: None, **kwargs
    )


def test_a_successful_send_reports_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 1, "request": "abc"})

    provider = _provider(handler)
    result = provider.send(PushoverMessage(title="SPCX — Entry setup active", message="Price: $146.18"))

    assert result.success is True
    assert result.error is None


def test_invalid_credentials_are_reported_without_leaking_them():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": 0, "errors": ["application token is invalid"]})

    provider = _provider(handler)
    result = provider.send(PushoverMessage(title="t", message="m"))

    assert result.success is False
    assert result.error == "invalid_credentials"
    assert "test-app-token" not in (result.error or "")
    assert "test-user-key" not in (result.error or "")


def test_a_rejected_request_status_zero_is_reported_as_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 0, "errors": ["user identifier is invalid"]})

    provider = _provider(handler)
    result = provider.send(PushoverMessage(title="t", message="m"))

    assert result.success is False
    assert result.error == "rejected"


def test_a_network_error_retries_once_then_reports_failure():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ConnectError("boom")

    provider = _provider(handler, max_retries=1)
    result = provider.send(PushoverMessage(title="t", message="m"))

    assert result.success is False
    assert result.error == "network_error"
    assert attempts["count"] == 2  # initial attempt + 1 retry


def test_a_timeout_is_reported_as_failure_not_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    provider = _provider(handler, max_retries=0)
    result = provider.send(PushoverMessage(title="t", message="m"))

    assert result.success is False
    assert result.error == "timeout"


def test_rate_limited_then_succeeds_on_retry():
    responses = [httpx.Response(429), httpx.Response(200, json={"status": 1})]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    provider = _provider(handler, max_retries=1)
    result = provider.send(PushoverMessage(title="t", message="m"))

    assert result.success is True


def test_a_5xx_response_is_retried_then_reported_as_a_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    provider = _provider(handler, max_retries=1)
    result = provider.send(PushoverMessage(title="t", message="m"))

    assert result.success is False
    assert result.error == "server_error_503"


def test_the_outbound_request_never_logs_or_echoes_credentials_in_an_exception():
    """Not a log-capture test (send() never logs anything itself -- the
    CALLER logs, see app.alerts.push) -- this proves the only place the
    credentials appear at all is the outbound request body, never in any
    exception message raised along the way."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated DNS failure for api.pushover.net")

    provider = _provider(handler, max_retries=0)
    try:
        result = provider.send(PushoverMessage(title="t", message="m"))
    except Exception as exc:  # pragma: no cover -- send() must never raise
        pytest.fail(f"send() raised instead of returning a failure result: {exc}")
    assert result.success is False


@pytest.mark.parametrize("field", ["token", "user"])
def test_credentials_are_sent_as_form_fields_not_url_query_params(field):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"status": 1})

    provider = _provider(handler)
    provider.send(PushoverMessage(title="t", message="m"))

    assert "test-app-token" not in captured["url"]
    assert "test-user-key" not in captured["url"]
    assert field in captured["body"]
