import math
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.core.idempotency import IdempotencyContext, require_idempotency
from app.core.permissions import can_view_tenant_finance
from app.models.tenants import Tenant, User, UserRole
from app.models.wallet import WalletTxnStatus
from app.schemas.v1.common import PaginatedResponse
from app.schemas.v1.wallet import (
    AdminOfflineCreditRequest,
    CodSettlementResponse,
    RechargeRejectRequest,
    UpiConfirmRequest,
    UpiIntentRequest,
    UpiIntentResponse,
    UpiRechargeStatusResponse,
    VerifyUtrRequest,
    VerifyUtrResponse,
    WalletIntegrityAuditResponse,
    WalletOverviewResponse,
    WalletTransactionRead,
)
from app.services.integrity_audit import (
    IntegrityAuditService,
    get_integrity_audit_service,
)
from app.services.receipt_pdf import ReceiptPdfGenerator
from app.services.shipment import ShipmentService, get_shipment_service
from app.services.wallet import WalletService, get_wallet_service

router = APIRouter()

TENANT_ADMIN_ROLES = (UserRole.admin, UserRole.owner)
IDEMPOTENCY_UPI_INTENT = "wallet.recharge.upi_intent"
IDEMPOTENCY_UPI_CONFIRM = "wallet.recharge.confirm"
IDEMPOTENCY_UPI_APPROVE = "wallet.recharge.approve"
IDEMPOTENCY_UPI_REJECT = "wallet.recharge.reject"
IDEMPOTENCY_VERIFY_UTR = "wallet.recharge.verify_utr"
IDEMPOTENCY_ADMIN_CREDIT = "wallet.recharge.admin_credit"
IDEMPOTENCY_SETTLE_COD = "wallet.settle_cod"


def _require_tenant_admin(user: User, detail: str) -> None:
    """
    Raises 403 unless the caller is a Tenant Admin / Owner.

    Args:
        user: The authenticated user resolved by `get_current_active_user`.
        detail: Human-readable reason returned in the 403 response body.
    """
    if user.role not in TENANT_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail=detail)


@router.get("", response_model=WalletOverviewResponse)
@router.get("/", response_model=WalletOverviewResponse, include_in_schema=False)
async def get_wallet_overview(
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Fetch the logged-in user's Unified Wallet balance (starts strictly at ₹0.00),
    tenant's DB-configured wallet & pricing settings, and ledger summary.
    """
    return await wallet_service.get_wallet_overview(
        user=current_user, tenant=current_tenant
    )


@router.get("/audit-integrity", response_model=WalletIntegrityAuditResponse)
async def audit_wallet_integrity(
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    audit_service: IntegrityAuditService = Depends(get_integrity_audit_service),
):
    """
    Cross-checks wallet balances, completed ledger rows, prepaid GST invoices,
    COD remittances, and active pickup manifests for zero-discrepancy integrity.
    F-04: finance staff only (Owner / Admin / Read-only), run on demand; customers never
    see internal audit codes.
    """
    if not can_view_tenant_finance(current_user):
        raise HTTPException(
            status_code=403,
            detail="The ledger integrity check is available to finance staff only.",
        )
    return await audit_service.audit_tenant_integrity(
        user=current_user, tenant=current_tenant
    )


@router.get(
    "/transactions",
    response_model=PaginatedResponse[WalletTransactionRead],
)
async def list_wallet_transactions(
    tab: str = Query(
        default="all",
        description="Tab filter: 'spends' (Spends & Refunds), 'recharges', or 'all'",
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user_id: Optional[uuid.UUID] = Query(
        default=None,
        description=(
            "Owner / Admin / Read-Only only: narrow the tenant-wide ledger to one user. "
            "Ignored for other roles (they always see only their own wallet)."
        ),
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    List paginated wallet transactions.

    Owner / Admin / Read-Only staff see every user's transactions in the tenant
    (each row carries `user_email`); everyone else sees only their own.
    """
    items, total = await wallet_service.list_user_transactions(
        user=current_user,
        tenant=current_tenant,
        tab=tab,
        page=page,
        size=size,
        filter_user_id=user_id,
    )
    pages = math.ceil(total / size) if size > 0 else 0
    parsed = [_to_transaction_read(item) for item in items]
    return PaginatedResponse(
        items=parsed, total=total, page=page, size=size, pages=pages
    )


def _to_transaction_read(txn) -> WalletTransactionRead:
    """Maps a ledger row to its DTO, carrying the transient `user_email` attribute."""
    dto = WalletTransactionRead.model_validate(txn)
    dto.user_email = getattr(txn, "user_email", None)
    return dto


@router.post("/recharge/upi-intent", response_model=UpiIntentResponse)
async def create_upi_recharge_intent(
    payload: UpiIntentRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_UPI_INTENT)),
):
    """
    Generates an NPCI UPI intent URI + Base64 SVG QR Code for zero-fee UPI recharge.
    """
    if idem.replay is not None:
        return idem.replay
    body = await wallet_service.create_upi_intent(
        user=current_user, tenant=current_tenant, payload=payload
    )
    await idem.store(body)
    return body


@router.get(
    "/recharge/{transaction_id}/status",
    response_model=UpiRechargeStatusResponse,
)
async def get_upi_recharge_status(
    transaction_id: uuid.UUID,
    auto_complete: Optional[bool] = Query(
        default=None,
        description="Optional parameter (status check only returns COMPLETED once verified)",
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Polls the status of a UPI QR recharge transaction (`PENDING` -> `COMPLETED`).
    """
    return await wallet_service.check_upi_recharge_status(
        user=current_user,
        tenant=current_tenant,
        transaction_id=transaction_id,
        auto_complete=auto_complete,
    )


@router.post(
    "/recharge/{transaction_id}/confirm",
    response_model=UpiRechargeStatusResponse,
)
async def confirm_upi_recharge(
    transaction_id: uuid.UUID,
    payload: Optional[UpiConfirmRequest] = None,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_UPI_CONFIRM)),
):
    """
    Records 'I Have Paid' on a UPI QR recharge intent (with optional 12-digit UTR for reference).
    Keeps the transaction in PENDING status awaiting Admin approval.
    """
    if idem.replay is not None:
        return idem.replay
    body = await wallet_service.confirm_upi_recharge(
        user=current_user,
        tenant=current_tenant,
        transaction_id=transaction_id,
        payload=payload,
    )
    await idem.store(body)
    return body


@router.get(
    "/admin/pending-recharges",
    response_model=list[WalletTransactionRead],
)
async def list_tenant_pending_recharges(
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Admin-only endpoint returning all PENDING recharge requests across the tenant
    where a user has clicked 'I Have Paid'.
    """
    return await wallet_service.list_tenant_pending_recharges(
        admin_user=current_user,
        tenant=current_tenant,
    )


@router.post(
    "/recharge/{transaction_id}/approve",
    response_model=UpiRechargeStatusResponse,
)
async def approve_pending_recharge(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_UPI_APPROVE)),
):
    """
    Admin-only endpoint that approves a PENDING recharge request and merges
    its amount into the user's main Unified Wallet balance.
    """
    if idem.replay is not None:
        return idem.replay
    body = await wallet_service.approve_pending_recharge(
        admin_user=current_user,
        tenant=current_tenant,
        transaction_id=transaction_id,
    )
    await idem.store(body)
    return body


@router.post(
    "/recharge/{transaction_id}/reject",
    response_model=UpiRechargeStatusResponse,
)
async def reject_pending_recharge(
    transaction_id: uuid.UUID,
    payload: Optional[RechargeRejectRequest] = None,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_UPI_REJECT)),
):
    """
    Admin-only endpoint that rejects a PENDING recharge request without crediting the wallet.
    The optional reason is shown to the merchant in their passbook (A-15).
    """
    if idem.replay is not None:
        return idem.replay
    body = await wallet_service.reject_pending_recharge(
        admin_user=current_user,
        tenant=current_tenant,
        transaction_id=transaction_id,
        reason=payload.reason if payload else None,
    )
    await idem.store(body)
    return body


@router.post("/admin/credit", response_model=VerifyUtrResponse)
async def record_admin_offline_wallet_credit(
    payload: AdminOfflineCreditRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_ADMIN_CREDIT)),
):
    """
    Owner/Admin manual wallet credit when a customer pays offline (NEFT / IMPS / RTGS /
    direct UPI / cheque / cash; #558 3b). Immediately creates a COMPLETED RECHARGE
    ledger entry and an official Wallet Advance Receipt Voucher (`REC-...`).
    """
    _require_tenant_admin(
        current_user,
        "Only Tenant Owners and Admins can record offline wallet credits.",
    )
    if idem.replay is not None:
        return idem.replay
    body = await wallet_service.record_admin_offline_credit(
        admin_user=current_user, tenant=current_tenant, payload=payload
    )
    await idem.store(body)
    return body


@router.post("/recharge/verify-utr", response_model=VerifyUtrResponse)
async def verify_upi_utr_recharge(
    payload: VerifyUtrRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_VERIFY_UTR)),
):
    """
    Admin "approve with UTR": verifies a 12-digit UPI UTR (with duplicate replay
    protection) against a MERCHANT's pending recharge request and credits that
    merchant's wallet. Never the caller's own wallet (B-06 maker-checker).

    Restricted to Tenant Admins / Owners.
    """
    if idem.replay is not None:
        return idem.replay
    _require_tenant_admin(
        current_user, "Only Tenant Admins can verify UTR recharges directly."
    )
    body = await wallet_service.verify_utr_recharge(
        user=current_user, tenant=current_tenant, payload=payload
    )
    await idem.store(body)
    return body


@router.post("/settle-cod", response_model=CodSettlementResponse)
async def settle_cod_shipments_to_wallet(
    merchant_user_id: Optional[uuid.UUID] = Query(
        default=None,
        description=(
            "Owner / Admin only: settle this merchant's delivered COD into the merchant's "
            "wallet (default: the caller's own bookings)."
        ),
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_SETTLE_COD)),
):
    """
    Settles Delivered (COMPLETED), not-yet-remitted COD shipments into a Unified Wallet.
    Owner / Admin only; customers are paid in the finance team's COD remittance cycle (403).
    """
    if idem.replay is not None:
        return idem.replay
    body = await wallet_service.settle_cod_to_wallet(
        user=current_user, tenant=current_tenant, merchant_user_id=merchant_user_id
    )
    await idem.store(body)
    return body


@router.get("/transactions/{txn_id}/receipt-pdf")
async def download_wallet_transaction_receipt_pdf(
    txn_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Generates a printable A4 PDF Receipt / Credit Note / GST Freight Invoice (HSN/SAC 996812)
    for a specific COMPLETED wallet transaction.
    """
    txn = await wallet_service.wallet_repo.get_transaction_by_id(
        txn_id=txn_id, tenant_id=current_tenant.id
    )
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    is_finance_viewer = can_view_tenant_finance(current_user)
    if not is_finance_viewer and txn.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn.status != WalletTxnStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Cannot generate an official payment receipt for an incomplete or unpaid transaction.",
        )

    shipment = None
    if txn.shipment_id:
        shipment = await shipment_service.shipment_repo.get_shipment_full_details(
            txn.shipment_id, current_tenant.id
        )

    # The receipt is issued to the wallet owner, not to the admin downloading it.
    receipt_user = current_user
    if txn.user_id != current_user.id:
        receipt_user = (
            await wallet_service.wallet_repo.session.get(User, txn.user_id)
        ) or current_user

    pdf_buffer = ReceiptPdfGenerator.generate_wallet_receipt_pdf(
        txn=txn,
        tenant=current_tenant,
        user=receipt_user,
        shipment=shipment,
    )
    filename = f"Receipt_{txn.receipt_number}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/export/csv")
async def export_wallet_ledger_csv(
    user_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Owner / Admin / Read-Only only: export a single user's ledger.",
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Streams a CSV export of the wallet ledger (tenant-wide for Owner / Admin /
    Read-Only staff, otherwise the caller's own wallet).
    """
    csv_io = await wallet_service.export_transactions_csv(
        user=current_user, tenant=current_tenant, filter_user_id=user_id
    )
    filename = f"Wallet_Ledger_{current_tenant.slug}.csv"
    return StreamingResponse(
        iter([csv_io.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
