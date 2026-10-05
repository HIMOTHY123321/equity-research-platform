"""Phase 17 (§1/§27/§75/§76): market-data ENTITLEMENT is a fact about the
configured provider ACCOUNT -- never inferred from either of the two
things this codebase could otherwise mistake it for:

- "the provider CODE supports streaming" (app.market_data.capabilities
  .ProviderCapabilities) -- that's a fact about the implementation, true
  regardless of which account's key is configured.
- "the WebSocket handshake authenticated successfully" (app.live
  .massive_streaming) -- that only proves the key is valid, never which
  plan tier it belongs to. Massive's API does not expose an "am I
  entitled to real-time streaming" call (see docs/decisions/0018), so
  this is deliberately explicit/operator-configured rather than probed.

This is also completely separate from app.billing.entitlements (which
gates in-app FEATURES like the Validation Lab AI summary by the
authenticated USER's plan) -- a PRO app user does not grant the backend a
licensed exchange feed. See docs/decisions/0021 for the full rationale
and the activation checklist for when a real licensed account exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EntitlementStatus(str, Enum):
    ENTITLED = "entitled"
    NOT_ENTITLED = "not_entitled"
    UNKNOWN = "unknown"
    MISCONFIGURED = "misconfigured"
    # Phase 19.1: Twelve Data's Basic/free plan grants WebSocket access to
    # only a limited, discovered-at-runtime set of symbols -- genuinely
    # different from Massive's account-wide "entitled or not" model, so
    # this needs its own honest label rather than being folded into
    # ENTITLED (which would overstate it) or NOT_ENTITLED (which would
    # hide that real, live data IS flowing for the symbols that succeeded).
    TRIAL_ONLY = "trial_only"
    # A distinct state from NOT_ENTITLED: the account/key may well be
    # entitled, but its request budget is currently exhausted -- retrying
    # immediately would only make it worse. See
    # app.market_data.twelve_data_streaming for what sets this.
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True)
class MarketDataEntitlement:
    provider: str
    status: EntitlementStatus
    reason: str

    @property
    def confirmed(self) -> bool:
        # TRIAL_ONLY still means genuine, provider-confirmed real-time data
        # is flowing for at least one symbol -- REAL TIME may be shown for
        # that symbol's stream (Phase 19.1 §6); it is RATE_LIMITED/
        # NOT_ENTITLED/UNKNOWN/MISCONFIGURED that must never satisfy this.
        return self.status in (EntitlementStatus.ENTITLED, EntitlementStatus.TRIAL_ONLY)


def resolve_streaming_entitlement(
    *, provider_name: str, api_key: str, streaming_entitled_flag: Optional[bool]
) -> MarketDataEntitlement:
    """The one place streaming entitlement is decided. Never returns
    ENTITLED except on an explicit, operator-set `True` -- an API key
    being merely present (or the socket merely authenticating) is
    deliberately insufficient."""
    normalized_provider = provider_name.lower()

    if normalized_provider in ("twelve_data", "hybrid"):
        # Phase 19.1: deliberately never resolves ENTITLED/TRIAL_ONLY here,
        # even with a key present -- a valid Basic/free key proves nothing
        # about which symbols (if any) carry real WebSocket access, and
        # there is no "streaming_entitled_flag" for this provider to check
        # (see app.config.Settings' docstring for why). This UNKNOWN state
        # is only ever upgraded at runtime, once genuine subscription
        # acknowledgements arrive, via LiveMarketService reading
        # TwelveDataStreamingProvider.entitlement_hint() -- never here.
        if not api_key:
            return MarketDataEntitlement(
                provider=normalized_provider,
                status=EntitlementStatus.UNKNOWN,
                reason="TWELVE_DATA_API_KEY is not configured -- no account to check entitlement for.",
            )
        return MarketDataEntitlement(
            provider=normalized_provider,
            status=EntitlementStatus.UNKNOWN,
            reason=(
                "A Twelve Data API key is configured, but real-time streaming entitlement has "
                "not yet been confirmed -- a valid key does not guarantee WebSocket access on "
                "the Basic/free plan. This resolves once a genuine subscription attempt "
                "succeeds or is rejected."
            ),
        )

    if normalized_provider != "massive":
        return MarketDataEntitlement(
            provider=normalized_provider,
            status=EntitlementStatus.NOT_ENTITLED,
            reason=f"Provider {normalized_provider!r} has no streaming implementation in this codebase.",
        )

    if not api_key:
        return MarketDataEntitlement(
            provider=normalized_provider,
            status=EntitlementStatus.UNKNOWN,
            reason="MASSIVE_API_KEY is not configured -- no account to check entitlement for.",
        )

    if streaming_entitled_flag is None:
        return MarketDataEntitlement(
            provider=normalized_provider,
            status=EntitlementStatus.UNKNOWN,
            reason=(
                "MASSIVE_STREAMING_ENTITLED is not set. A valid API key alone does not "
                "confirm real-time streaming access -- Massive's API does not expose plan "
                "tier. Set this explicitly once the account's real-time entitlement has "
                "been confirmed by an eligible contracting party (see docs/deployment.md)."
            ),
        )

    if streaming_entitled_flag:
        return MarketDataEntitlement(
            provider=normalized_provider,
            status=EntitlementStatus.ENTITLED,
            reason="MASSIVE_STREAMING_ENTITLED=true (operator-confirmed real-time access).",
        )

    return MarketDataEntitlement(
        provider=normalized_provider,
        status=EntitlementStatus.NOT_ENTITLED,
        reason="MASSIVE_STREAMING_ENTITLED=false (operator-confirmed no real-time access).",
    )
