import logging
import math
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.core.idempotency import IdempotencyContext, require_idempotency
from app.core.money import to_money, to_weight
from app.core.permissions import is_tenant_staff
from app.models.pickups import PickupRequest, PickupStatus, ShipmentType
from app.models.tenants import Tenant, User
from app.schemas.v1.common import PaginatedResponse
from app.schemas.v1.pickups import (
    AppointmentUpdate,
    NdrExceptionResolveRequest,
    PickupCreate,
    PickupRead,
    PickupUpdate,
    ShipmentActivityRead,
)
from app.schemas.v1.pricing import (
    AdminShipmentChargeCreate,
    CarrierBillingRead,
    CarrierBillingUpdate,
    ValuationRequest,
    ValuationResponse,
)
from app.schemas.v1.repricing import (
    ChargeAdjustmentRead,
    MeasurementCreate,
    MeasurementResult,
    RejectedField,
    RepricePreviewResponse,
)
from app.schemas.v1.wallet import WeightAuditRequest
from app.services.delhivery_modules import (
    DelhiveryModulesService,
    get_delhivery_modules_service,
)
from app.services.exceptions import ExceptionsService, get_exceptions_service
from app.services.label import LabelGenerator
from app.services.pricing.carrier_billing import (
    apply_admin_shipment_charge,
    get_carrier_billing,
    update_carrier_billing,
)
from app.services.pricing.quote_service import valuation
from app.services.receipt_pdf import ReceiptPdfGenerator
from app.services.repricing import (
    MeasurementInput,
    RepricingError,
    RepricingService,
    assert_edit_allowed,
    edit_fields_from_update,
    get_repricing_service,
)
from app.services.shipment import ShipmentService, get_shipment_service
from app.services.wallet import WalletService, get_wallet_service

# --- Setup Logger ---
logger = logging.getLogger(__name__)

router = APIRouter()

# Idempotency scopes (H-4): one name per money POST, stable across releases.
IDEMPOTENCY_CREATE = "shipments.create"
IDEMPOTENCY_UPDATE = "shipments.update"
IDEMPOTENCY_CANCEL = "shipments.cancel"
IDEMPOTENCY_AUDIT_WEIGHT = "shipments.audit_weight"
IDEMPOTENCY_MEASUREMENTS = "shipments.measurements"
IDEMPOTENCY_ADMIN_CHARGE = "shipments.admin_charge"


def _serialize_shipment(shipment: PickupRequest, user: User) -> PickupRead:
    """Serializes a shipment to `PickupRead`, exposing `transporter_name` only to tenant staff."""
    ShipmentService._attach_staff_transporter(shipment, user)
    body = PickupRead.model_validate(shipment)
    if not is_tenant_staff(user):
        body.transporter_name = None
    return body


def _to_measurement_input(payload: MeasurementCreate) -> MeasurementInput:
    """
    Maps the HTTP measurement body onto reprice-core's frozen `MeasurementInput`.

    Args:
        payload: Validated request body (exactly one of packages / weight_kg).

    Returns:
        The service input.
    """
    return MeasurementInput(
        source=payload.source,
        packages=tuple(payload.packages or ()),
        weight_only_kg=(
            to_weight(payload.weight_kg) if payload.weight_kg is not None else None
        ),
        evidence_urls=tuple(payload.evidence_urls),
        remark=payload.remark,
        override_total_price=(
            to_money(payload.override_total_price)
            if payload.override_total_price is not None
            else None
        ),
    )


@router.post("", response_model=PickupRead, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    *,
    payload: PickupCreate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_CREATE, required=True)),
):
    """
    Create a new Shipment.

    - **Authentication**: Requires a valid JWT and X-Tenant-Slug header.
    - **Validation**: Checks if "Saved Address IDs" belong to the current tenant.
    - **Transaction**: Creates Addresses (if new), Packages, and Shipment in one go.
    - **Idempotency**: the `Idempotency-Key` header is REQUIRED (A-17); a retry with the same key
      replays the first response, so a slow network never books twice (H-4).
    - **Pricing**: always re-priced on the server; `expected_total` ≠ fresh total → 409 PRICE_CHANGED.
    """
    if idem.replay is not None:
        return idem.replay
    logger.info(
        f"API Request: Create Shipment for Tenant '{current_tenant.slug}' by User '{current_user.email}'"
    )

    logger.debug(
        f"Payload: order_ref={payload.order_reference_id}, packages={len(payload.packages)}"
    )

    shipment = await shipment_service.create_shipment(
        payload=payload,
        tenant=current_tenant,
        user_id=current_user.id,
        actor=current_user,
    )

    logger.info(f"API Success: Created Shipment ID {shipment.id}")
    body = _serialize_shipment(shipment, current_user)
    await idem.store(body, status_code=status.HTTP_201_CREATED)
    return body


@router.put("/{shipment_id}", response_model=PickupRead)
@router.patch("/{shipment_id}", response_model=PickupRead)
async def update_shipment(
    *,
    shipment_id: uuid.UUID,
    payload: PickupUpdate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_UPDATE)),
):
    """
    Update an existing Shipment.

    - **Permissions**: staff edit within the hard blocks; a merchant edits their own
      shipment per the Delhivery One matrix (B9, enforced by the service): COD amount +
      consignee up to and including In Transit, only the consignee contact at Out for
      delivery (H-12), declared boxes while Ready to ship, service type before pickup (H-8).
    - **Features**:
        - Updates fields (Status, Date, etc.)
        - Syncs Packages (Add/Update/Remove)
        - Syncs Documents
        - Re-prices through RepricingService only when a price input changed
        - **Auto-generates Audit Log** (ShipmentActivity)
    - **Errors**: refused changes are 400/403 with a `detail` string.
    """
    if idem.replay is not None:
        return idem.replay
    logger.info(f"API Request: Update Shipment {shipment_id} by {current_user.email}")

    updated_shipment = await shipment_service.update_shipment(
        shipment_id=shipment_id,
        payload=payload,
        user=current_user,
        tenant_id=current_tenant.id,
    )

    logger.info(f"API Success: Updated Shipment {shipment_id}")
    body = _serialize_shipment(updated_shipment, current_user)
    await idem.store(body)
    return body


# CHANGED: Removed the "/" to prevent 307 Redirects from the proxy
@router.get("", response_model=PaginatedResponse[PickupRead])
async def list_shipments(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
    is_b2b: Optional[bool] = Query(
        default=None, description="Optional filter for B2B vs B2C shipments"
    ),
    status: Optional[List[PickupStatus]] = Query(
        default=None,
        description="Optional status filter (repeat the param for several statuses).",
    ),
    shipment_type: Optional[ShipmentType] = Query(
        default=None,
        description="Optional filter for FORWARD vs REVERSE shipments.",
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    List Shipments (Paginated).
    - **Admins**: View ALL shipments.
    - **Customers**: View ONLY their created shipments.
    """
    # Unpack the Tuple
    items, total = await shipment_service.list_my_shipments(
        user=current_user,
        tenant_id=current_tenant.id,
        page=page,
        size=size,
        is_b2b=is_b2b,
        statuses=status,
        shipment_type=shipment_type,
    )

    # Calculate total pages
    total_pages = math.ceil(total / size) if size > 0 else 0

    parsed_items = [_serialize_shipment(item, current_user) for item in items]

    return PaginatedResponse(
        items=parsed_items, total=total, page=page, size=size, pages=total_pages
    )


@router.get("/export/csv")
async def export_shipments_csv(
    is_b2b: Optional[bool] = Query(
        default=None, description="Optional filter for B2B vs B2C shipments CSV export"
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Streams a CSV export of shipments for the current user / tenant.
    """
    csv_io = await shipment_service.export_shipments_csv(
        user=current_user, tenant_id=current_tenant.id, is_b2b=is_b2b
    )
    suffix = "_B2B" if is_b2b is True else ("_B2C" if is_b2b is False else "")
    filename = f"Shipments_{current_tenant.slug}{suffix}.csv"
    return StreamingResponse(
        iter([csv_io.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{shipment_id}/timeline", response_model=List[ShipmentActivityRead])
async def get_shipment_timeline(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Get Audit Timeline.
    - **Restricted**: Only Admins/Owners can view this full technical history.
    """
    return await shipment_service.get_timeline(
        shipment_id=shipment_id, user=current_user, tenant_id=current_tenant.id
    )


@router.get("/{shipment_id}", response_model=PickupRead)
async def get_shipment_details(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Get full details of a specific shipment.
    - **Admins**: Can view any shipment.
    - **Customers**: Can only view their own.
    """
    # 1. Fetch the raw shipment from the service
    shipment = await shipment_service.get_shipment_details(
        shipment_id=shipment_id, user=current_user, tenant_id=current_tenant.id
    )

    # 2. Convert the SQLModel into our Pydantic Response Schema
    return _serialize_shipment(shipment, current_user)


@router.get("/{shipment_id}/label")
async def download_shipping_label(
    shipment_id: uuid.UUID,
    label_format: str = Query(
        default="a4",
        pattern="^(a4|thermal_4x2)$",
        description="Label format (a4 or thermal_4x2)",
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Generates and downloads a PDF Shipping Label (Consolidated A4/4x6 or 4x2 Thermal).
    """
    # 1. Fetch shipment (Ensures Security/Auth rules apply!)
    shipment = await shipment_service.get_shipment_details(
        shipment_id=shipment_id, user=current_user, tenant_id=current_tenant.id
    )
    shipment_service.assert_label_available(shipment)

    # 2. Generate PDF
    pdf_buffer = LabelGenerator.generate_pdf(
        shipment, current_tenant, label_format=label_format
    )

    # 3. Stream it to the client
    suffix = "_Thermal4x2" if label_format == "thermal_4x2" else ""
    filename = f"Label_{shipment.tracking_id}{suffix}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/valuation", response_model=ValuationResponse)
async def shipment_valuation(
    payload: ValuationRequest,
    current_user: User = Depends(get_current_active_user),
) -> ValuationResponse:
    """
    D-06: the declared goods total (value + tax) and whether it needs an e-way bill.
    Read-only; the booking recomputes the same total server-side.
    """
    return valuation(payload.shipment_value, payload.shipment_tax_value)


@router.get("/{shipment_id}/invoice-pdf")
async def download_shipment_invoice_pdf(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
    wallet_service: WalletService = Depends(get_wallet_service),
    billing_service: DelhiveryModulesService = Depends(get_delhivery_modules_service),
):
    """
    Generates a printable A4 GST Tax Invoice PDF (HSN/SAC 996812) for a shipment.
    It prints the shipment's GST register row (same number and tax split as
    Finances > Invoices); legacy shipments without one get it allocated now.
    """
    shipment = await shipment_service.get_shipment_details(
        shipment_id=shipment_id, user=current_user, tenant_id=current_tenant.id
    )
    shipment_service.assert_invoice_available(shipment)
    invoice = await billing_service.get_or_issue_shipment_invoice(
        shipment=shipment, tenant=current_tenant
    )
    txn = await wallet_service.wallet_repo.get_transaction_by_shipment_id(
        shipment_id=shipment.id, tenant_id=current_tenant.id
    )
    pdf_buffer = ReceiptPdfGenerator.generate_shipment_invoice_pdf(
        shipment=shipment,
        tenant=current_tenant,
        user=current_user,
        invoice=invoice,
        txn=txn,
    )
    filename = f"Invoice_{shipment.tracking_id}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{shipment_id}/audit-weight", response_model=PickupRead)
async def audit_shipment_weight(
    shipment_id: uuid.UUID,
    payload: WeightAuditRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_AUDIT_WEIGHT)),
):
    """
    Legacy hub "Audit Scale": a weight-only HUB measurement. Kept as a thin wrapper of
    `POST /shipments/{id}/measurements` (the declared box sizes stay; the re-pricing
    service settles any delta both ways with a DEBIT/CREDIT_NOTE).
    """
    if idem.replay is not None:
        return idem.replay
    updated = await shipment_service.audit_shipment_weight(
        shipment_id=shipment_id,
        audited_weight_kg=payload.audited_weight_kg,
        user=current_user,
        tenant=current_tenant,
        override_total_price=payload.override_total_price,
    )
    body = _serialize_shipment(updated, current_user)
    await idem.store(body)
    return body


@router.post("/{shipment_id}/measurements", response_model=MeasurementResult)
async def record_shipment_measurement(
    shipment_id: uuid.UUID,
    payload: MeasurementCreate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
    repricing_service: RepricingService = Depends(get_repricing_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_MEASUREMENTS)),
):
    """
    Records the measured parcel (rider at pickup, hub, admin) and re-prices the shipment
    on it (Delhivery One `weight-dispute`: the measured parcel is the billing basis).

    - **Permissions**: operations user / admin / owner, never read-only (service-enforced).
    - **Body**: exactly one of `packages` (full measurement) or `weight_kg` (weight-only).
    - **Idempotency**: optional `Idempotency-Key` header (H-4).
    - **Errors**: 400 for a ₹0 quote (H-7) or a refused state, 422 for an invalid measurement.
    """
    if idem.replay is not None:
        return idem.replay
    shipment, result = await shipment_service.record_measurement(
        shipment_id,
        current_user,
        current_tenant,
        _to_measurement_input(payload),
        idempotency_key=idem.key,
    )
    adjustment = None
    if result.adjustment_id is not None:
        views = await repricing_service.list_adjustment_views(shipment.id, current_tenant.id)
        adjustment = next(
            (
                ChargeAdjustmentRead.model_validate(view)
                for view in views
                if view.id == result.adjustment_id
            ),
            None,
        )
    body = MeasurementResult(
        shipment=_serialize_shipment(shipment, current_user), adjustment=adjustment
    )
    await idem.store(body)
    return body


@router.post("/{shipment_id}/reprice-preview", response_model=RepricePreviewResponse)
async def preview_shipment_reprice(
    shipment_id: uuid.UUID,
    payload: PickupUpdate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
    repricing_service: RepricingService = Depends(get_repricing_service),
):
    """
    Dry run of `PATCH /shipments/{id}` with the same body (changed fields only): old vs
    new price, chargeable weight, wallet effect and GST note type. Nothing is written.

    Refusals (H-7 ₹0 quote, H-8 service type after pickup, H-9 collectible after delivery,
    H-12 / B9 merchant edit window) come back as 200 with `rejected_fields`, so the edit
    dialog can show them next to the field.
    """
    shipment = await shipment_service.get_shipment_details(
        shipment_id=shipment_id, user=current_user, tenant_id=current_tenant.id
    )
    payment = shipment.payment_details
    current_total = to_money(payment.total_logistics_cost if payment else None)
    current_weight = to_weight(payment.chargeable_weight if payment else None)
    current_breakdown = payment.pricing_breakdown if payment else {}
    try:
        assert_edit_allowed(
            shipment, edit_fields_from_update(payload, shipment), current_user
        )
        change = await repricing_service.change_from_update(
            shipment, payload, current_tenant.id, current_user
        )
        if change is None:
            return RepricePreviewResponse.unchanged(
                shipment.id, current_total, current_weight, current_breakdown
            )
        preview = await repricing_service.preview(
            shipment, current_tenant, change, current_user
        )
    except RepricingError as error:
        return RepricePreviewResponse.unchanged(
            shipment.id,
            current_total,
            current_weight,
            current_breakdown,
            rejected=[RejectedField.from_error(error)],
        )
    return RepricePreviewResponse.from_preview(preview)


@router.get("/{shipment_id}/charges", response_model=List[ChargeAdjustmentRead])
async def list_shipment_charges(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
    repricing_service: RepricingService = Depends(get_repricing_service),
):
    """
    Charges history of a shipment, oldest first: every re-price with its reason,
    old → new total, wallet transaction and GST note (Delhivery One wallet ledger per AWB).
    Merchants see only their own shipments (404 otherwise).
    """
    shipment = await shipment_service.get_shipment_details(
        shipment_id=shipment_id, user=current_user, tenant_id=current_tenant.id
    )
    views = await repricing_service.list_adjustment_views(shipment.id, current_tenant.id)
    return [ChargeAdjustmentRead.model_validate(view) for view in views]


@router.post("/{shipment_id}/cancel", response_model=PickupRead)
async def cancel_shipment(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_CANCEL)),
):
    """
    Cancel an existing Shipment.

    - **Permissions**: Admins/Owners or the creator of the shipment.
    - **Before pickup**: cancelled with a full prepaid refund + CREDIT_NOTE.
    - **After pickup**: the service converts it to RTO (Delhivery One `cancel-forward-order`).
    - **Idempotency**: optional `Idempotency-Key` header (H-4).
    """
    if idem.replay is not None:
        return idem.replay
    logger.info(f"API Request: Cancel Shipment {shipment_id} by {current_user.email}")

    updated_shipment = await shipment_service.cancel_shipment(
        shipment_id=shipment_id,
        user=current_user,
        tenant_id=current_tenant.id,
    )

    logger.info(f"API Success: Cancelled Shipment {shipment_id}")
    body = _serialize_shipment(updated_shipment, current_user)
    await idem.store(body)
    return body


@router.patch("/{shipment_id}/appointment", response_model=PickupRead)
async def update_appointment(
    *,
    shipment_id: uuid.UUID,
    payload: AppointmentUpdate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    shipment_service: ShipmentService = Depends(get_shipment_service),
):
    """
    Update Appointment.
    Validates shipment status is OPEN or IN_TRANSIT. Saves details and logs a ShipmentActivity.
    """
    logger.info(f"API Request: Update Appointment for Shipment {shipment_id} by {current_user.email}")

    updated_shipment = await shipment_service.update_appointment(
        shipment_id=shipment_id,
        payload=payload,
        user=current_user,
        tenant_id=current_tenant.id,
    )

    logger.info(f"API Success: Updated Appointment for Shipment {shipment_id}")
    return _serialize_shipment(updated_shipment, current_user)


@router.post("/{shipment_id}/resolve-exception", response_model=PickupRead)
async def resolve_shipment_exception(
    *,
    shipment_id: uuid.UUID,
    payload: NdrExceptionResolveRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    exceptions_service: ExceptionsService = Depends(get_exceptions_service),
):
    """
    Legacy: resolve an active Delivery Exception / NDR on a Shipment.
    Maps legacy actions (DELIVER_WITHOUT_APPOINTMENT, UPDATE_CONSIGNEE_DETAILS,
    RETURN_TO_SENDER, HOLD_SHIPMENT) or any NdrAction value onto the
    `POST /exceptions/{id}/actions` pipeline (same matrix validation and audit log).
    """
    logger.info(
        f"API Request: Resolve Exception ({payload.action}) for Shipment {shipment_id} by {current_user.email}"
    )
    updated_shipment = await exceptions_service.resolve_legacy(
        shipment_id=shipment_id,
        payload=payload,
        user=current_user,
        tenant=current_tenant,
    )
    logger.info(f"API Success: Resolved Exception for Shipment {shipment_id}")
    return _serialize_shipment(updated_shipment, current_user)


@router.get("/{shipment_id}/carrier-billing", response_model=CarrierBillingRead)
async def read_shipment_carrier_billing(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    repricing_service: RepricingService = Depends(get_repricing_service),
) -> CarrierBillingRead:
    """
    Staff-only view of the carrier booking (service option, carrier AWB, charged weight/amount,
    and invoice-gap verdict; DESIGN.md v4 D4 / Q13).
    """
    return await get_carrier_billing(
        repricing_service.session, shipment_id, current_tenant.id, current_user
    )


@router.put("/{shipment_id}/carrier-billing", response_model=CarrierBillingRead)
async def save_shipment_carrier_billing(
    shipment_id: uuid.UUID,
    payload: CarrierBillingUpdate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    repricing_service: RepricingService = Depends(get_repricing_service),
) -> CarrierBillingRead:
    """
    Records the carrier AWB, optional charged weight (`CARRIER` measurement), and charged amount
    (Owner, Admin, and Operations staff only).
    """
    return await update_carrier_billing(
        repricing_service.session, shipment_id, current_tenant, payload, current_user
    )


@router.post("/{shipment_id}/admin-charge", response_model=CarrierBillingRead)
async def create_admin_shipment_charge(
    shipment_id: uuid.UUID,
    payload: AdminShipmentChargeCreate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    repricing_service: RepricingService = Depends(get_repricing_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_ADMIN_CHARGE)),
) -> CarrierBillingRead:
    """
    Applies a direct Owner/Admin price adjustment to a shipment (#558 3c):
    debits the customer's wallet, updates `total_logistics_cost`, issues a GST Debit Note,
    and returns the updated `CarrierBillingRead` view.
    """
    if idem.replay is not None:
        return idem.replay
    body = await apply_admin_shipment_charge(
        repricing_service.session, shipment_id, current_tenant, payload, current_user
    )
    await idem.store(body)
    return body
