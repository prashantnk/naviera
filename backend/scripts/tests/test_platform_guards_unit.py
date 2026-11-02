"""Pure unit tests for WP7 platform guards: auth rate limiting (B-05), security headers and
hidden API docs in production (B-11), and the readiness probe (G-06)."""

from types import SimpleNamespace
from typing import Dict, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core import rate_limit
from app.core.rate_limit import RateRule, SlidingWindowLimiter, client_ip
from app.core.security import TokenPayload
from app.middleware import security_headers as headers_module
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.repositories.health import database_is_reachable
from app.schemas.v1.tenants import PasswordLoginRequest
from app.services.notifications import (
    clear_recent_notifications,
    get_recent_notifications,
    notify_ndr_raised,
    notify_wallet_recharge_status,
    notify_weight_debit,
)
from app.services.tenants import TenantService


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _request(peer: Optional[str], forwarded: Optional[str] = None) -> SimpleNamespace:
    headers: Dict[str, str] = {}
    if forwarded:
        headers[rate_limit.FORWARDED_FOR_HEADER] = forwarded
    client = SimpleNamespace(host=peer) if peer else None
    return SimpleNamespace(headers=headers, client=client)


def test_sliding_window_blocks_then_recovers() -> None:
    clock = _Clock()
    limiter = SlidingWindowLimiter(clock=clock)
    rule = RateRule(max_hits=3, window_seconds=60)
    key = ("login-account", "a@b.in")
    assert [limiter.hit(key, rule) for _ in range(3)] == [None, None, None]
    retry = limiter.hit(key, rule)
    assert retry == 60
    clock.now += 30
    assert limiter.hit(key, rule) == 30  # refused attempts are not recorded
    clock.now += 31
    assert limiter.hit(key, rule) is None


def test_keys_are_independent() -> None:
    limiter = SlidingWindowLimiter(clock=_Clock())
    rule = RateRule(max_hits=1, window_seconds=60)
    assert limiter.hit(("login-ip", "1.1.1.1"), rule) is None
    assert limiter.hit(("login-ip", "2.2.2.2"), rule) is None
    assert limiter.hit(("login-ip", "1.1.1.1"), rule) is not None


def test_client_ip_prefers_first_forwarded_entry() -> None:
    assert client_ip(_request("10.0.0.5", "203.0.113.9, 10.0.0.1")) == "203.0.113.9"
    assert client_ip(_request("198.51.100.4")) == "198.51.100.4"
    assert client_ip(_request(None)) == rate_limit.UNKNOWN_CLIENT


def test_login_guard_raises_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rate_limit, "auth_limiter", SlidingWindowLimiter(clock=_Clock()))
    monkeypatch.setattr(rate_limit, "is_production", lambda: True)
    request = _request("10.0.0.5", "203.0.113.9")
    payload = PasswordLoginRequest(email="Victim@Example.com", password="x" * 8)
    for _ in range(rate_limit.LOGIN_PER_ACCOUNT.max_hits):
        rate_limit.guard_login(request, payload)
    with pytest.raises(HTTPException) as exc:
        rate_limit.guard_login(request, payload)
    assert exc.value.status_code == 429
    assert "Too many attempts" in exc.value.detail
    assert int(exc.value.headers["Retry-After"]) > 0


def test_local_calls_are_exempt_only_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    loopback = _request("127.0.0.1")
    monkeypatch.setattr(rate_limit, "is_production", lambda: False)
    assert rate_limit.is_local_direct_call(loopback)
    assert not rate_limit.is_local_direct_call(_request("203.0.113.9"))
    monkeypatch.setattr(rate_limit, "is_production", lambda: True)
    assert not rate_limit.is_local_direct_call(loopback)


def test_security_headers_hsts_only_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(headers_module, "is_production", lambda: False)
    local = headers_module.security_headers()
    assert local["X-Frame-Options"] == "DENY"
    assert local["X-Content-Type-Options"] == "nosniff"
    assert "Strict-Transport-Security" not in local
    monkeypatch.setattr(headers_module, "is_production", lambda: True)
    assert "Strict-Transport-Security" in headers_module.security_headers()


class _Session:
    def __init__(self, fail: bool) -> None:
        self.fail = fail

    async def exec(self, _statement) -> None:
        if self.fail:
            raise ConnectionError("db down")


@pytest.mark.asyncio
async def test_readiness_probe_reports_database_state() -> None:
    assert await database_is_reachable(_Session(fail=False)) is True
    assert await database_is_reachable(_Session(fail=True)) is False


@pytest.mark.asyncio
async def test_b04_invite_linking_requires_verified_email_and_invited_prefix() -> None:
    """B-04: Unverified emails cannot claim invited rows; already-linked rows cannot be hijacked."""
    tenant = Tenant(id=uuid4(), name="Logismart", slug="logismart", settings={})
    repo = MagicMock()
    repo.get_user_by_supabase_id_and_tenant_id = AsyncMock(return_value=None)

    invited_row = User(
        id=uuid4(),
        email="ops@logismart.in",
        supabase_user_id="invited:ops@logismart.in",
        tenant_id=tenant.id,
        role=UserRole.operations_user,
        service_scope=ServiceScope.BOTH,
        is_active=True,
    )
    repo.get_user_by_email_and_tenant_id = AsyncMock(return_value=invited_row)
    svc = TenantService(repo)

    # Unverified token -> 403
    unverified_token = TokenPayload(
        sub="new-sub-1",
        email="ops@logismart.in",
        aud="authenticated",
        email_verified=False,
    )
    with pytest.raises(HTTPException) as exc_unverified:
        await svc.get_or_create_user(token_data=unverified_token, tenant=tenant)
    assert exc_unverified.value.status_code == 403

    # Already-linked row with a different sub -> 403
    linked_row = User(
        id=uuid4(),
        email="ops@logismart.in",
        supabase_user_id="existing-real-sub",
        tenant_id=tenant.id,
        role=UserRole.operations_user,
        service_scope=ServiceScope.BOTH,
        is_active=True,
    )
    repo.get_user_by_email_and_tenant_id = AsyncMock(return_value=linked_row)
    verified_token = TokenPayload(
        sub="attacker-sub-2",
        email="ops@logismart.in",
        aud="authenticated",
        email_verified=True,
    )
    with pytest.raises(HTTPException) as exc_hijack:
        await svc.get_or_create_user(token_data=verified_token, tenant=tenant)
    assert exc_hijack.value.status_code == 403


@pytest.mark.asyncio
async def test_g10_update_tenant_settings_expected_version_conflict() -> None:
    """G-10: Stale expected_version on update_tenant_settings returns 409 Conflict."""
    tenant_id = uuid4()
    tenant = Tenant(id=tenant_id, name="Logismart", slug="logismart", settings={})
    admin = User(
        id=uuid4(),
        email="owner@logismart.in",
        supabase_user_id="owner-sub",
        tenant_id=tenant_id,
        role=UserRole.owner,
        service_scope=ServiceScope.BOTH,
        is_active=True,
    )
    repo = MagicMock()
    repo.get_tenant_for_update = AsyncMock(return_value=tenant)
    repo.next_settings_version = AsyncMock(return_value=6)  # current version is 5
    svc = TenantService(repo)

    with pytest.raises(HTTPException) as exc:
        await svc.update_tenant_settings(
            tenant_id,
            admin,
            {"expected_version": 4, "brand": {"show_logo": True}},
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_i02_transactional_notifications_dispatched() -> None:
    """I-02: NDR raised, recharge status, and weight debit notifications dispatch and record."""
    clear_recent_notifications()
    n1 = await notify_ndr_raised(
        merchant_email="seller@logismart.in",
        tracking_id="LS2610309999",
        reason="CONSIGNEE_UNAVAILABLE",
        remark="Customer did not answer phone",
    )
    assert n1 is not None
    assert n1.event_type == "NDR_RAISED"

    n2 = await notify_wallet_recharge_status(
        merchant_email="seller@logismart.in",
        amount_inr=2500.0,
        status_label="APPROVED",
        utr="123456789012",
    )
    assert n2 is not None
    assert n2.event_type == "WALLET_RECHARGE_APPROVED"

    n3 = await notify_weight_debit(
        merchant_email="seller@logismart.in",
        tracking_id="LS2610309999",
        old_weight_kg=0.5,
        new_weight_kg=2.0,
        debit_inr=90.0,
    )
    assert n3 is not None
    assert n3.event_type == "WEIGHT_DEBIT"
    assert len(get_recent_notifications()) == 3

