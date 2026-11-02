"""
Pure unit tests (no database) for who may settle delivered COD into a wallet
(coordinator decision 2026-11-01, b2c-money): customers are paid in the finance team's
remittance cycle (403); Owner / Admin settle their own or a merchant's COD.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.tenants import UserRole
from app.services.wallet import (
    COD_MERCHANT_NOT_FOUND_DETAIL,
    CUSTOMER_COD_SETTLE_DETAIL,
    WalletService,
)

TENANT = SimpleNamespace(id=uuid.uuid4())
OTHER_TENANT_ID = uuid.uuid4()


def _user(role: UserRole, tenant_id: uuid.UUID = TENANT.id) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role, tenant_id=tenant_id, email=f"{role.value}@x.in")


def _service(stored_user=None) -> WalletService:
    repo = MagicMock()
    repo.session = SimpleNamespace(get=AsyncMock(return_value=stored_user))
    return WalletService(wallet_repo=repo)


@pytest.mark.asyncio
async def test_customer_cannot_self_settle_cod() -> None:
    with pytest.raises(HTTPException) as exc:
        await _service()._resolve_cod_settlement_owner(_user(UserRole.customer), TENANT, None)
    assert exc.value.status_code == 403
    assert exc.value.detail == CUSTOMER_COD_SETTLE_DETAIL


@pytest.mark.asyncio
async def test_customer_cannot_settle_for_someone_else_either() -> None:
    with pytest.raises(HTTPException) as exc:
        await _service()._resolve_cod_settlement_owner(
            _user(UserRole.customer), TENANT, uuid.uuid4()
        )
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "role", [UserRole.operations_user, UserRole.support_user, UserRole.read_only_user]
)
@pytest.mark.asyncio
async def test_non_finance_staff_cannot_settle(role: UserRole) -> None:
    with pytest.raises(HTTPException) as exc:
        await _service()._resolve_cod_settlement_owner(_user(role), TENANT, None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_settles_own_cod_by_default() -> None:
    admin = _user(UserRole.admin)
    svc = _service()
    assert await svc._resolve_cod_settlement_owner(admin, TENANT, None) == admin.id
    assert await svc._resolve_cod_settlement_owner(admin, TENANT, admin.id) == admin.id
    svc.wallet_repo.session.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_settles_a_merchant_of_the_same_tenant() -> None:
    merchant = _user(UserRole.customer)
    svc = _service(stored_user=merchant)
    owner = _user(UserRole.owner)
    assert await svc._resolve_cod_settlement_owner(owner, TENANT, merchant.id) == merchant.id


@pytest.mark.parametrize("stored", [None, _user(UserRole.customer, tenant_id=OTHER_TENANT_ID)])
@pytest.mark.asyncio
async def test_unknown_or_foreign_merchant_is_404(stored) -> None:
    svc = _service(stored_user=stored)
    with pytest.raises(HTTPException) as exc:
        await svc._resolve_cod_settlement_owner(_user(UserRole.admin), TENANT, uuid.uuid4())
    assert exc.value.status_code == 404
    assert exc.value.detail == COD_MERCHANT_NOT_FOUND_DETAIL
