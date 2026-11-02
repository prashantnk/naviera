"""Unit tests: staff finance views label each tenant-wide row with its merchant (staff-finance journey)."""

import uuid
from datetime import date, datetime
from types import SimpleNamespace
from typing import Dict, List, Optional, Sequence

import pytest

from app.models.delhivery_modules import CodRemittance
from app.models.tenants import UserRole
from app.schemas.v1.delhivery_modules import CodRemittanceRead
from app.services.delhivery_modules import DelhiveryModulesService

TENANT_ID = uuid.uuid4()
MERCHANT_A = uuid.uuid4()
MERCHANT_B = uuid.uuid4()
EMAILS = {MERCHANT_A: "a@shop.in", MERCHANT_B: "b@shop.in"}


def _remittance(merchant_id: uuid.UUID, number: str) -> CodRemittance:
    """A detached remittance row owned by `merchant_id`."""
    return CodRemittance(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        merchant_user_id=merchant_id,
        remittance_number=number,
        processed_date=date(2026, 11, 1),
        bank_utr="UTR123456789",
        total_remittance=100.0,
        total_orders=1,
        shipment_breakdown=[],
        created_at=datetime(2026, 11, 1, 10, 0, 0),
    )


class _FakeRepo:
    """Records email lookups and serves canned remittance lists."""

    def __init__(self, rows: List[CodRemittance]):
        self.rows = rows
        self.email_calls: List[Sequence[uuid.UUID]] = []
        self.list_scope: Optional[uuid.UUID] = None

    async def get_user_emails(
        self, tenant_id: uuid.UUID, user_ids: Sequence[uuid.UUID]
    ) -> Dict[uuid.UUID, str]:
        assert tenant_id == TENANT_ID
        self.email_calls.append(list(user_ids))
        return {uid: EMAILS[uid] for uid in user_ids if uid in EMAILS}

    async def list_remittances(self, tenant_id, merchant_user_id=None, search=None, processed_date=None):
        self.list_scope = merchant_user_id
        return list(self.rows)

    async def get_remittance_by_identifier(self, tenant_id, identifier):
        return next((r for r in self.rows if r.remittance_number == identifier), None)


def _user(role: UserRole, user_id: Optional[uuid.UUID] = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=role, tenant_id=TENANT_ID)


@pytest.mark.asyncio
async def test_staff_remittance_list_carries_merchant_email_in_one_lookup() -> None:
    repo = _FakeRepo([_remittance(MERCHANT_A, "R1"), _remittance(MERCHANT_B, "R2"), _remittance(MERCHANT_A, "R3")])
    service = DelhiveryModulesService(repo)  # type: ignore[arg-type]

    rows = await service.list_remittances(user=_user(UserRole.read_only_user), tenant_id=TENANT_ID)

    assert repo.list_scope is None  # tenant-wide for finance staff
    assert len(repo.email_calls) == 1
    dtos = [CodRemittanceRead.model_validate(r) for r in rows]
    assert [d.merchant_email for d in dtos] == ["a@shop.in", "b@shop.in", "a@shop.in"]


@pytest.mark.asyncio
async def test_remittance_detail_carries_merchant_email_and_unknown_user_is_none() -> None:
    orphan = uuid.uuid4()
    repo = _FakeRepo([_remittance(orphan, "R9")])
    service = DelhiveryModulesService(repo)  # type: ignore[arg-type]

    row = await service.get_remittance(user=_user(UserRole.owner), tenant_id=TENANT_ID, identifier="R9")

    assert CodRemittanceRead.model_validate(row).merchant_email is None


@pytest.mark.asyncio
async def test_customer_still_sees_only_own_rows() -> None:
    repo = _FakeRepo([_remittance(MERCHANT_A, "R1")])
    service = DelhiveryModulesService(repo)  # type: ignore[arg-type]

    await service.list_remittances(user=_user(UserRole.customer, MERCHANT_A), tenant_id=TENANT_ID)

    assert repo.list_scope == MERCHANT_A


def test_read_dto_without_attached_email_defaults_to_none() -> None:
    assert CodRemittanceRead.model_validate(_remittance(MERCHANT_A, "R1")).merchant_email is None
