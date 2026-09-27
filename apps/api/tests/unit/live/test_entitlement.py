"""Phase 17 (§1/§27/§78): resolve_streaming_entitlement is the single
decision function streaming entitlement is built around -- these tests
cover every (provider, key, flag) branch of its state machine, with
particular emphasis on the never-return-ENTITLED-without-an-explicit-True
invariant the rest of Phase 17 (LiveMarketService.real_time_available())
depends on.
"""

from __future__ import annotations

from app.live.entitlement import EntitlementStatus, MarketDataEntitlement, resolve_streaming_entitlement


def test_non_massive_provider_is_never_entitled():
    result = resolve_streaming_entitlement(
        provider_name="yfinance", api_key="", streaming_entitled_flag=True
    )
    assert result.status == EntitlementStatus.NOT_ENTITLED
    assert result.confirmed is False


def test_massive_without_api_key_is_unknown():
    result = resolve_streaming_entitlement(
        provider_name="massive", api_key="", streaming_entitled_flag=None
    )
    assert result.status == EntitlementStatus.UNKNOWN
    assert result.confirmed is False


def test_massive_with_key_but_unset_flag_is_unknown_not_entitled():
    """A valid key alone must never be treated as proof of entitlement."""
    result = resolve_streaming_entitlement(
        provider_name="massive", api_key="sk-real-key", streaming_entitled_flag=None
    )
    assert result.status == EntitlementStatus.UNKNOWN
    assert result.confirmed is False


def test_massive_with_key_and_explicit_true_flag_is_entitled():
    result = resolve_streaming_entitlement(
        provider_name="massive", api_key="sk-real-key", streaming_entitled_flag=True
    )
    assert result.status == EntitlementStatus.ENTITLED
    assert result.confirmed is True


def test_massive_with_key_and_explicit_false_flag_is_not_entitled():
    result = resolve_streaming_entitlement(
        provider_name="massive", api_key="sk-real-key", streaming_entitled_flag=False
    )
    assert result.status == EntitlementStatus.NOT_ENTITLED
    assert result.confirmed is False


def test_provider_name_is_normalized_case_insensitively():
    result = resolve_streaming_entitlement(
        provider_name="MASSIVE", api_key="sk-real-key", streaming_entitled_flag=True
    )
    assert result.provider == "massive"
    assert result.status == EntitlementStatus.ENTITLED


def test_reason_is_always_a_nonempty_string():
    for provider, key, flag in [
        ("yfinance", "", True),
        ("massive", "", None),
        ("massive", "k", None),
        ("massive", "k", True),
        ("massive", "k", False),
    ]:
        result = resolve_streaming_entitlement(
            provider_name=provider, api_key=key, streaming_entitled_flag=flag
        )
        assert isinstance(result.reason, str)
        assert result.reason


def test_only_entitled_status_reports_confirmed_true():
    for status in EntitlementStatus:
        entitlement = MarketDataEntitlement(provider="massive", status=status, reason="x")
        assert entitlement.confirmed == (status == EntitlementStatus.ENTITLED)
