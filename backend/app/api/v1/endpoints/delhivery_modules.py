import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.core.idempotency import IdempotencyContext, require_idempotency
from app.models.tenants import Tenant, User
from app.schemas.v1.delhivery_modules import (
    BillingInvoiceCreate,
    BillingInvoiceRead,
    CodRemittanceCreate,
    CodRemittancePreview,
    CodRemittanceRead,
    SupportTicketCreate,
    SupportTicketDetailRead,
    SupportTicketMessageCreate,
    SupportTicketRead,
    SupportTicketStatusUpdate,
    SupportTicketSummary,
    WeightDisputeClaimCreate,
    WeightDisputeRead,
    WeightDisputeResolveRequest,
)
from app.services.delhivery_modules import (
    DelhiveryModulesService,
    get_delhivery_modules_service,
)
from app.services.shipment import ShipmentService, get_shipment_service

remittances_router = APIRouter()
invoices_router = APIRouter()
support_tickets_router = APIRouter()
disputes_router = APIRouter()

IDEMPOTENCY_CREATE_REMITTANCE = "remittances.create"
IDEMPOTENCY_CREATE_INVOICE = "invoices.create"
IDEMPOTENCY_RAISE_WEIGHT_CLAIMS = "disputes.weight_mismatch.claims"
IDEMPOTENCY_RESOLVE_WEIGHT_DISPUTE = "disputes.weight_mismatch.resolve"


# ------------------------------------------------------------------
# 1. Remittances (/api/v1/remittances)
# ------------------------------------------------------------------


@remittances_router.get("", response_model=List[CodRemittanceRead])
async def list_remittances(
    search: Optional[str] = Query(default=None),
    processed_date: Optional[date] = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Lists COD Remittance rows for the current tenant."""
    return await service.list_remittances(
        user=current_user,
        tenant_id=current_user.tenant_id,
        search=search,
        processed_date=processed_date,
    )


@remittances_router.post(
    "", response_model=CodRemittanceRead, status_code=status.HTTP_201_CREATED
)
async def create_remittance(
    payload: CodRemittanceCreate,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_CREATE_REMITTANCE)),
):
    """Creates a COD Remittance batch (Admin only)."""
    if idem.replay is not None:
        return idem.replay
    row = await service.create_remittance(
        admin_user=current_user,
        tenant_id=current_user.tenant_id,
        payload=payload,
    )
    body = CodRemittanceRead.model_validate(row)
    await idem.store(body, status_code=status.HTTP_201_CREATED)
    return body


@remittances_router.get("/pending", response_model=CodRemittancePreview)
async def preview_pending_remittance(
    merchant_user_id: uuid.UUID = Query(...),
    shipment_ids: Optional[List[uuid.UUID]] = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """
    A-06: the AWBs one merchant can be paid for now (server amounts) and the payout total
    of the ticked `shipment_ids` (all when omitted), plus whether the payout is on hold
    because their wallet is negative (A-05). Admin only.
    """
    return await service.preview_remittance(
        admin_user=current_user,
        tenant_id=current_user.tenant_id,
        merchant_user_id=merchant_user_id,
        selected_ids=shipment_ids,
    )


@remittances_router.get("/{identifier}/csv")
async def download_remittance_csv(
    identifier: str,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Streams the AWB breakdown CSV for a COD Remittance."""
    remit_number, csv_stream = await service.export_remittance_csv(
        user=current_user,
        tenant_id=current_user.tenant_id,
        identifier=identifier,
    )
    filename = f"remittance_{remit_number}_awb.csv"
    return StreamingResponse(
        iter([csv_stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@remittances_router.get("/{identifier}", response_model=CodRemittanceRead)
async def get_remittance_detail(
    identifier: str,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Lookup a COD Remittance by UUID or remittance_number."""
    return await service.get_remittance(
        user=current_user,
        tenant_id=current_user.tenant_id,
        identifier=identifier,
    )


# ------------------------------------------------------------------
# 2. Invoices (/api/v1/invoices)
# ------------------------------------------------------------------


@invoices_router.get("", response_model=List[BillingInvoiceRead])
async def list_billing_invoices(
    note_type: Optional[str] = Query(
        default=None, description="Filter by INVOICE, CREDIT_NOTE, or DEBIT_NOTE"
    ),
    search: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Lists BillingInvoice rows for the current tenant."""
    return await service.list_invoices(
        user=current_user,
        tenant_id=current_user.tenant_id,
        note_type=note_type,
        search=search,
    )


@invoices_router.post(
    "", response_model=BillingInvoiceRead, status_code=status.HTTP_201_CREATED
)
async def create_billing_invoice(
    payload: BillingInvoiceCreate,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_CREATE_INVOICE)),
):
    """Issues a new GST Invoice, Credit Note, or Debit Note (Admin only)."""
    if idem.replay is not None:
        return idem.replay
    row = await service.create_invoice(
        admin_user=current_user,
        tenant_id=current_user.tenant_id,
        payload=payload,
    )
    body = BillingInvoiceRead.model_validate(row)
    await idem.store(body, status_code=status.HTTP_201_CREATED)
    return body


@invoices_router.get("/{identifier}/pdf")
async def download_billing_invoice_pdf(
    identifier: str,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Generates a printable A4 GST Invoice PDF."""
    inv_number, pdf_buffer = await service.generate_invoice_pdf(
        user=current_user,
        tenant=current_tenant,
        identifier=identifier,
    )
    filename = f"invoice_{inv_number}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@invoices_router.get("/{identifier}/transactions-csv")
async def download_billing_invoice_transactions_csv(
    identifier: str,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Streams the transaction list CSV for a BillingInvoice."""
    inv_number, csv_stream = await service.export_invoice_transactions_csv(
        user=current_user,
        tenant_id=current_user.tenant_id,
        identifier=identifier,
    )
    filename = f"invoice_{inv_number}_transactions.csv"
    return StreamingResponse(
        iter([csv_stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@invoices_router.get("/{identifier}", response_model=BillingInvoiceRead)
async def get_billing_invoice_detail(
    identifier: str,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Lookup a BillingInvoice by UUID or invoice_number."""
    return await service.get_invoice(
        user=current_user,
        tenant_id=current_user.tenant_id,
        identifier=identifier,
    )


# ------------------------------------------------------------------
# 3. Support Tickets (/api/v1/support-tickets)
# ------------------------------------------------------------------


@support_tickets_router.get("", response_model=List[SupportTicketRead])
async def list_support_tickets(
    status: Optional[str] = Query(
        default=None, description="Filter by OPEN, RESOLVED, or CLOSED"
    ),
    search: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Lists SupportTicket rows (Customer sees own; Admin sees all in tenant)."""
    return await service.list_tickets(
        user=current_user,
        tenant_id=current_user.tenant_id,
        status_filter=status,
        search=search,
    )


@support_tickets_router.post(
    "", response_model=SupportTicketDetailRead, status_code=status.HTTP_201_CREATED
)
async def create_support_ticket(
    payload: SupportTicketCreate,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Creates a SupportTicket with an initial thread message."""
    return await service.create_ticket(
        user=current_user,
        tenant_id=current_user.tenant_id,
        payload=payload,
    )


@support_tickets_router.get("/summary", response_model=SupportTicketSummary)
async def get_support_ticket_summary(
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Home-dashboard Support card counters (declared before `/{ticket_id}`)."""
    return await service.get_ticket_summary(
        user=current_user, tenant_id=current_user.tenant_id
    )


@support_tickets_router.get("/{ticket_id}", response_model=SupportTicketDetailRead)
async def get_support_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Returns a SupportTicket and all thread messages."""
    return await service.get_ticket_detail(
        user=current_user,
        tenant_id=current_user.tenant_id,
        ticket_id=ticket_id,
    )


@support_tickets_router.post(
    "/{ticket_id}/messages", response_model=SupportTicketDetailRead
)
async def add_support_ticket_message(
    ticket_id: str,
    payload: SupportTicketMessageCreate,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Appends a reply message to a SupportTicket (reopening RESOLVED tickets on customer reply)."""
    return await service.add_ticket_message(
        user=current_user,
        tenant_id=current_user.tenant_id,
        ticket_id=ticket_id,
        payload=payload,
    )


@support_tickets_router.patch(
    "/{ticket_id}/status", response_model=SupportTicketDetailRead
)
async def update_support_ticket_status(
    ticket_id: str,
    payload: SupportTicketStatusUpdate,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Updates SupportTicket status (OPEN, RESOLVED, CLOSED)."""
    return await service.update_ticket_status(
        user=current_user,
        tenant_id=current_user.tenant_id,
        ticket_id=ticket_id,
        payload=payload,
    )


# ------------------------------------------------------------------
# 4. Weight Disputes (/api/v1/disputes/weight-mismatch)
# ------------------------------------------------------------------


@disputes_router.get("/weight-mismatch", response_model=List[WeightDisputeRead])
async def list_weight_mismatch_disputes(
    search: Optional[str] = Query(default=None),
    claim_status: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Lists WeightDispute rows for the current tenant."""
    return await service.list_weight_disputes(
        user=current_user,
        tenant_id=current_user.tenant_id,
        search=search,
        claim_status=claim_status,
    )


@disputes_router.post(
    "/weight-mismatch/claims", response_model=List[WeightDisputeRead]
)
async def raise_weight_mismatch_claims(
    payload: WeightDisputeClaimCreate,
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_RAISE_WEIGHT_CLAIMS)),
):
    """Raises a weight mismatch claim on one or more AWB tracking IDs."""
    if idem.replay is not None:
        return idem.replay
    rows = await service.raise_weight_claims(
        user=current_user,
        tenant_id=current_user.tenant_id,
        payload=payload,
    )
    body = [WeightDisputeRead.model_validate(r) for r in rows]
    await idem.store(body)
    return body


@disputes_router.patch(
    "/weight-mismatch/{dispute_id}/resolve", response_model=WeightDisputeRead
)
async def resolve_weight_mismatch_dispute(
    dispute_id: uuid.UUID,
    payload: WeightDisputeResolveRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
    shipment_service: ShipmentService = Depends(get_shipment_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_RESOLVE_WEIGHT_DISPUTE)),
):
    """Accepts or rejects a weight mismatch claim (Admin only)."""
    if idem.replay is not None:
        return idem.replay
    row = await service.resolve_weight_dispute(
        admin_user=current_user,
        tenant_id=current_tenant.id,
        dispute_id=dispute_id,
        payload=payload,
        claim_settler=lambda d: shipment_service.settle_accepted_weight_claim(
            d, current_tenant, current_user
        ),
    )
    body = WeightDisputeRead.model_validate(row)
    await idem.store(body)
    return body


@disputes_router.get("/weight-mismatch/export/csv")
async def export_weight_mismatch_csv(
    search: Optional[str] = Query(default=None),
    claim_status: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """Streams CSV of weight mismatch rows."""
    csv_stream = await service.export_weight_disputes_csv(
        user=current_user,
        tenant_id=current_user.tenant_id,
        search=search,
        claim_status=claim_status,
    )
    return StreamingResponse(
        iter([csv_stream.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="weight_mismatch_disputes.csv"'
        },
    )
