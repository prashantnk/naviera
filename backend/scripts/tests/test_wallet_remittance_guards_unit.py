"""Pure unit tests for WP5 wallet + remittance guards (A-05, A-06, A-14, A-16, A-24, B-06)."""

import uuid
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from fastapi import HTTPException

from app.models.tenants import UserRole
from app.models.wallet import (
    WALLET_COD_UTR_PREFIX,
    WalletTxnDirection,
    WalletTxnStatus,
    WalletTxnType,
    wallet_txn_direction,
)
from app.schemas.v1.delhivery_modules import CodRemittanceCreate
from app.schemas.v1.tenants import UserUpdate
from app.schemas.v1.wallet import (
    UpiConfirmRequest,
    VerifyUtrRequest,
    WalletTransactionRead,
)
from app.services.delhivery_modules import DelhiveryModulesService
from app.services.integrity_audit import IntegrityAuditService, _ShipmentLedger
from app.services.tenants import TenantService
from app.services.wallet import WalletService

# --- A-16 direction ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("txn_type", "direction"),
    [
        (WalletTxnType.RECHARGE, WalletTxnDirection.CREDIT),
        (WalletTxnType.REFUND, WalletTxnDirection.CREDIT),
        (WalletTxnType.COD_SETTLEMENT, WalletTxnDirection.CREDIT),
        (WalletTxnType.CHARGE_REVERSAL, WalletTxnDirection.CREDIT),
        (WalletTxnType.SPEND, WalletTxnDirection.DEBIT),
        (WalletTxnType.RTO_FREIGHT, WalletTxnDirection.DEBIT),
        (WalletTxnType.FREIGHT_COLLECTION, WalletTxnDirection.DEBIT),
        (WalletTxnType.ADDITIONAL_CHARGE, WalletTxnDirection.DEBIT),
        (WalletTxnType.WEIGHT_AUDIT_DEBIT, WalletTxnDirection.DEBIT),
    ],
)
def test_every_txn_type_has_one_direction(txn_type: WalletTxnType, direction: WalletTxnDirection) -> None:
    assert wallet_txn_direction(txn_type) == direction


def test_transaction_read_exposes_direction() -> None:
    row = WalletTransactionRead(
        id=uuid.uuid4(),
        wallet_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        txn_type=WalletTxnType.RTO_FREIGHT,
        service_category="B2C",
        opening_balance=10.0,
        amount=5.0,
        closing_balance=5.0,
        receipt_number="R",
        status=WalletTxnStatus.COMPLETED,
        created_at="2026-10-30T00:00:00",
    )
    assert row.model_dump()["direction"] == WalletTxnDirection.DEBIT


# --- A-05 / A-06 remittance ---------------------------------------------------------


def test_negative_wallet_blocks_bank_payout() -> None:
    assert DelhiveryModulesService._payout_blocked_reason(0.0) is None
    assert DelhiveryModulesService._payout_blocked_reason(250.0) is None
    reason = DelhiveryModulesService._payout_blocked_reason(-18000.0)
    assert reason and "-18,000.00" in reason


@pytest.mark.parametrize(
    "payload",
    [
        CodRemittanceCreate(bank_utr=" ", shipment_ids=[uuid.uuid4()], expected_total=1.0),
        CodRemittanceCreate(bank_utr="UTR1", merchant_user_id=uuid.uuid4(), expected_total=1.0),
        CodRemittanceCreate(bank_utr="UTR1", shipment_ids=[uuid.uuid4()]),
    ],
)
def test_remittance_needs_utr_ticked_awbs_and_total(payload: CodRemittanceCreate) -> None:
    with pytest.raises(HTTPException) as exc:
        DelhiveryModulesService._assert_remittance_request(payload)
    assert exc.value.status_code == 400


def test_valid_remittance_request_passes() -> None:
    DelhiveryModulesService._assert_remittance_request(
        CodRemittanceCreate(bank_utr="UTR1", shipment_ids=[uuid.uuid4()], expected_total=0.0)
    )


# --- A-24 single payout audit -------------------------------------------------------


def test_double_payout_is_flagged_and_wallet_settle_rows_are_not_bank_payouts() -> None:
    shipment_id = uuid.uuid4()
    line = {"shipment_id": str(shipment_id)}
    remittances = [
        SimpleNamespace(bank_utr="NEFT123", shipment_breakdown=[line]),
        SimpleNamespace(bank_utr=f"{WALLET_COD_UTR_PREFIX}AB12", shipment_breakdown=[line]),
    ]
    counts = IntegrityAuditService._bank_payout_counts(remittances)
    assert counts[str(shipment_id)] == 1
    service = IntegrityAuditService(wallet_repo=None)  # type: ignore[arg-type]
    shipment = SimpleNamespace(id=shipment_id, tracking_id="AWB1")
    once = _ShipmentLedger()
    assert service._check_single_payout(shipment, once, counts) == []
    twice = _ShipmentLedger()
    twice.txns.append(SimpleNamespace(txn_type=WalletTxnType.COD_SETTLEMENT))
    findings = service._check_single_payout(shipment, twice, counts)
    assert [f.category for f in findings] == ["COD_DOUBLE_PAYOUT"]


# --- B-06 roles ---------------------------------------------------------------------


def _user(role: UserRole, user_id: Optional[uuid.UUID] = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=role)


def test_only_owner_can_make_or_change_admins() -> None:
    admin = _user(UserRole.admin)
    customer = _user(UserRole.customer)
    with pytest.raises(HTTPException) as exc:
        TenantService._assert_owner_rules(admin, customer, UserUpdate(role=UserRole.admin))
    assert exc.value.status_code == 403
    other_admin = _user(UserRole.admin)
    with pytest.raises(HTTPException):
        TenantService._assert_owner_rules(admin, other_admin, UserUpdate(is_active=False))
    owner = _user(UserRole.owner)
    TenantService._assert_owner_rules(owner, customer, UserUpdate(role=UserRole.admin))
    TenantService._assert_owner_rules(admin, customer, UserUpdate(role=UserRole.operations_user))


def test_nobody_changes_own_role_or_deactivates_self() -> None:
    admin = _user(UserRole.admin)
    with pytest.raises(HTTPException) as exc:
        TenantService._assert_owner_rules(admin, admin, UserUpdate(role=UserRole.customer))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        TenantService._assert_owner_rules(admin, admin, UserUpdate(is_active=False))


# --- A-14 / B-06 recharge -----------------------------------------------------------


class _Repo:
    """Minimal async wallet repository double."""

    def __init__(self, txn: Any = None) -> None:
        self.txn = txn
        self.session = SimpleNamespace()

    async def get_transaction_by_id(self, txn_id: Any, tenant_id: Any = None) -> Any:
        return self.txn

    async def get_transaction_by_utr(self, utr: str) -> Any:
        return None

    async def get_or_create_wallet(self, **_: Any) -> Any:
        return SimpleNamespace(balance=0.0, id=uuid.uuid4())


@pytest.mark.asyncio
async def test_confirm_requires_a_12_digit_utr() -> None:
    user = _user(UserRole.customer)
    txn = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, status=WalletTxnStatus.PENDING)
    service = WalletService(_Repo(txn))  # type: ignore[arg-type]
    tenant = SimpleNamespace(id=uuid.uuid4(), settings={})
    for bad in (None, UpiConfirmRequest(), UpiConfirmRequest(utr_number="12345")):
        with pytest.raises(HTTPException) as exc:
            await service.confirm_upi_recharge(
                user=user, tenant=tenant, transaction_id=txn.id, payload=bad
            )
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_verify_utr_never_credits_the_callers_own_wallet() -> None:
    admin = _user(UserRole.admin)
    tenant = SimpleNamespace(id=uuid.uuid4())
    no_request = VerifyUtrRequest(utr_number="123456789012", amount=100.0)
    with pytest.raises(HTTPException) as exc:
        await WalletService(_Repo()).verify_utr_recharge(admin, tenant, no_request)  # type: ignore[arg-type]
    assert exc.value.status_code == 400
    own = SimpleNamespace(
        id=uuid.uuid4(), user_id=admin.id, txn_type=WalletTxnType.RECHARGE, status=WalletTxnStatus.PENDING
    )
    own_request = VerifyUtrRequest(utr_number="123456789012", transaction_id=own.id)
    with pytest.raises(HTTPException) as exc:
        await WalletService(_Repo(own)).verify_utr_recharge(admin, tenant, own_request)  # type: ignore[arg-type]
    assert exc.value.status_code == 403
