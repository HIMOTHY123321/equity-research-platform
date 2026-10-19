"""Phase 20: Pushover phone-push delivery -- the ONLY place this backend
ever talks to Pushover's API. Deliberately small: one message type, one
HTTP call, one bounded retry, modeled on the exact injectable-client +
bounded-retry convention app.market_data.twelve_data_provider already
uses for its own outbound HTTP calls (so this isn't a new pattern to
review, just the same one applied to a different provider).

The app token (global, from `app.config.Settings.pushover_app_token`) and
each user's own decrypted Pushover user key (per-user, see
app.alerts.push and app.notifications.secret_crypto) are passed in by the
caller for every call -- this module never reads settings/env itself, and
never logs, returns, or embeds either credential in any exception message
or `PushoverSendResult.error` string. A result's
`error` field is always one of a small set of category labels (e.g.
"invalid_credentials", "rate_limited", "network_error"), never the raw
response body (which, for an invalid-credentials response, could echo
back enough of the submitted token/user value to partially reconstruct
it)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_RETRIES = 1


@dataclass(frozen=True)
class PushoverMessage:
    title: str
    message: str
    url: Optional[str] = None
    url_title: Optional[str] = None


@dataclass(frozen=True)
class PushoverSendResult:
    success: bool
    error: Optional[str] = None
    """A short, secret-free category label -- never the raw response body
    or exception text. None when `success` is True."""


class PushoverProvider:
    def __init__(
        self,
        app_token: str,
        user_key: str,
        *,
        client: Optional[httpx.Client] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._app_token = app_token
        self._user_key = user_key
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._max_retries = max_retries
        self._sleep = sleep_fn

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def send(self, message: PushoverMessage) -> PushoverSendResult:
        """Never raises -- every failure mode (network error, timeout,
        rejected credentials, rate limit, malformed response) is caught
        here and returned as a `PushoverSendResult(success=False, ...)`.
        Callers (app.alerts.push) rely on this: a Pushover outage must
        never propagate into the Decision Engine's monitoring loop."""
        payload = {
            "token": self._app_token,
            "user": self._user_key,
            "title": message.title,
            "message": message.message,
        }
        if message.url:
            payload["url"] = message.url
        if message.url_title:
            payload["url_title"] = message.url_title

        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.post(PUSHOVER_API_URL, data=payload)
            except httpx.TimeoutException:
                if attempt > self._max_retries:
                    return PushoverSendResult(success=False, error="timeout")
                self._sleep(_backoff_seconds(attempt))
                continue
            except httpx.TransportError:
                if attempt > self._max_retries:
                    return PushoverSendResult(success=False, error="network_error")
                self._sleep(_backoff_seconds(attempt))
                continue

            if response.status_code == 429:
                if attempt > self._max_retries:
                    return PushoverSendResult(success=False, error="rate_limited")
                self._sleep(_backoff_seconds(attempt))
                continue
            if response.status_code in (401, 403):
                return PushoverSendResult(success=False, error="invalid_credentials")
            if response.status_code >= 500:
                if attempt > self._max_retries:
                    return PushoverSendResult(success=False, error=f"server_error_{response.status_code}")
                self._sleep(_backoff_seconds(attempt))
                continue
            if response.status_code != 200:
                return PushoverSendResult(success=False, error=f"http_error_{response.status_code}")

            try:
                body = response.json()
            except ValueError:
                return PushoverSendResult(success=False, error="malformed_response")
            if body.get("status") == 1:
                return PushoverSendResult(success=True)
            return PushoverSendResult(success=False, error="rejected")


def _backoff_seconds(attempt: int) -> float:
    return min(0.5 * (2 ** (attempt - 1)), 2.0)
