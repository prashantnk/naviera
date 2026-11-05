import logging
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.core.idempotency import IdempotencyContext, require_idempotency
from app.models.manifests import ManifestStatus, ServiceFlow
from app.models.tenants import Tenant, User
from app.schemas.v1.manifests import (
    EligibleShipmentRead,
    ManifestCreate,
    ManifestDispatchRequest,
    ManifestNotPickedRequest,
    ManifestResponse,
    ManifestShipmentsAdd,
    PickupCandidatesResponse,
)
from app.services.label import THERMAL_4X2_FORMAT, LabelGenerator
from app.services.manifests import ManifestService
from app.services.receipt_pdf import ReceiptPdfGenerator

logger = logging.getLogger(__name__)

router = APIRouter()

LABEL_FORMAT_PATTERN = f"^(a4|{THERMAL_4X2_FORMAT})$"
IDEMPOTENCY_DISPATCH = "manifests.dispatch"
"""Idempotency scope (H-4) of the dispatch POST, which may re-price LRs on measurements."""
IDEMPOTENCY_CANCEL = "manifests.cancel"
"""Idempotency scope (H-4) of the pickup-request cancel POST (double-click safe, J55)."""


@router.post("", response_model=ManifestResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=ManifestResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_manifest(
    *,
    payload: ManifestCreate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    Create a Pickup Request (B2C or B2B) with a generated 9-digit Pickup ID.
    Links the given OPEN shipment_ids (same flow + pickup location) and sets them ASSIGNED.
    """
    logger.info(f"Creating {payload.service_flow.value} Manifest for tenant {current_tenant.id}")
    service = ManifestService(session)
    return await service.create_manifest(
        payload, current_tenant.id, current_user=current_user
    )


@router.get("", response_model=List[ManifestResponse])
@router.get("/", response_model=List[ManifestResponse], include_in_schema=False)
async def list_manifests(
    *,
    service_flow: Optional[ServiceFlow] = Query(None, description="Filter by B2C or B2B pickup requests"),
    status_filter: Optional[ManifestStatus] = Query(None, alias="status", description="Filter by pickup status"),
    scheduled_date: Optional[date] = Query(None, description="Filter by exact pickup date"),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    List Pickup Requests for the current tenant (filtered by customer ownership when role=customer).
    """
    service = ManifestService(session)
    return await service.list_manifests(
        current_tenant.id,
        current_user=current_user,
        service_flow=service_flow,
        status_filter=status_filter,
        scheduled_date=scheduled_date,
    )


@router.get("/eligible-shipments", response_model=List[EligibleShipmentRead])
async def list_eligible_shipments(
    *,
    service_flow: ServiceFlow = Query(description="B2C or B2B"),
    pickup_address_id: uuid.UUID = Query(description="Selected pickup location"),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    OPEN (Ready to Ship) shipments of one flow that ship from the selected pickup location.
    Feeds the Create Pickup Request picker; the frontend must not filter on its own.
    """
    service = ManifestService(session)
    return await service.list_eligible_shipments(
        current_tenant.id,
        service_flow=service_flow,
        pickup_address_id=pickup_address_id,
        current_user=current_user,
    )


@router.get("/pickup-candidates", response_model=PickupCandidatesResponse)
async def get_pickup_candidates(
    *,
    shipment_ids: List[uuid.UUID] = Query(description="Selected shipment ids (repeat the parameter)"),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    Validates a Shipments-list selection (one flow, one pickup location, all OPEN) and returns
    SCHEDULED pickups from today onwards it can be added to (Delhivery "add to today's pickup").
    """
    service = ManifestService(session)
    return await service.get_pickup_candidates(
        shipment_ids, current_tenant.id, current_user=current_user
    )


@router.get("/{manifest_id}", response_model=ManifestResponse)
async def get_manifest(
    *,
    manifest_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    Get a single Pickup Request detail (customer-scoped; `pickup_otp` stripped for ops/support/readonly).
    """
    service = ManifestService(session)
    return await service.get_manifest(
        manifest_id, current_tenant.id, current_user=current_user
    )


@router.post("/{manifest_id}/shipments", response_model=ManifestResponse)
async def add_shipments_to_manifest(
    *,
    manifest_id: uuid.UUID,
    payload: ManifestShipmentsAdd,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    Add OPEN shipments to an existing SCHEDULED pickup (same flow + pickup location).
    """
    logger.info(f"Adding {len(payload.shipment_ids)} shipments to Manifest {manifest_id}")
    service = ManifestService(session)
    return await service.add_shipments(
        manifest_id, payload.shipment_ids, current_tenant.id, current_user=current_user
    )


@router.post("/{manifest_id}/cancel", response_model=ManifestResponse)
async def cancel_manifest(
    *,
    manifest_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_CANCEL)),
):
    """
    Cancel a SCHEDULED / OUT_FOR_PICKUP Manifest and release linked shipments back to OPEN status.
    An optional `Idempotency-Key` header replays the first response (H-4); an un-keyed second
    cancel is refused because the manifest is no longer cancellable.
    """
    if idem.replay is not None:
        return idem.replay
    logger.info(f"Cancelling Manifest {manifest_id} for tenant {current_tenant.id}")
    service = ManifestService(session)
    result = await service.cancel_manifest(
        manifest_id, current_tenant.id, current_user=current_user
    )
    body = ManifestResponse.model_validate(result)
    await idem.store(body)
    return body


@router.post("/{manifest_id}/out-for-pickup", response_model=ManifestResponse)
async def mark_manifest_out_for_pickup(
    *,
    manifest_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    Admin-only: SCHEDULED -> OUT_FOR_PICKUP (pickup executive is on the way).
    """
    service = ManifestService(session)
    return await service.mark_out_for_pickup(
        manifest_id, current_tenant.id, current_user=current_user
    )


@router.post("/{manifest_id}/not-picked", response_model=ManifestResponse)
async def mark_manifest_not_picked(
    *,
    manifest_id: uuid.UUID,
    payload: ManifestNotPickedRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    Admin-only: SCHEDULED/OUT_FOR_PICKUP -> NOT_PICKED with a reason.
    Linked shipments detach and revert ASSIGNED -> OPEN (Ready to Ship).
    """
    service = ManifestService(session)
    return await service.mark_not_picked(
        manifest_id, payload.failure_reason, current_tenant.id, current_user=current_user
    )


@router.post("/{manifest_id}/dispatch", response_model=ManifestResponse)
async def dispatch_manifest(
    *,
    manifest_id: uuid.UUID,
    payload: Optional[ManifestDispatchRequest] = Body(default=None),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_DISPATCH)),
):
    """
    Mark a scheduled Manifest as Picked Up / Dispatched (COMPLETED),
    transitioning picked shipments to IN_TRANSIT with a 6-digit delivery_otp and releasing unpicked shipments back to OPEN.

    Optional `measurements[]` carry the rider's "Actual pieces" per picked LR; each one is
    recorded as a PICKUP measurement and the LR is re-priced on it (plan B5). Because that
    moves money, an optional `Idempotency-Key` header replays the first response (H-4).
    """
    if idem.replay is not None:
        return idem.replay
    logger.info(f"Dispatching Manifest {manifest_id} for tenant {current_tenant.id}")
    service = ManifestService(session)
    dispatch_kwargs = (
        {"measurements": payload.measurements}
        if payload and payload.measurements is not None
        else {}
    )
    result = await service.dispatch_manifest(
        manifest_id=manifest_id,
        tenant_id=current_tenant.id,
        user_id=current_user.id,
        current_user=current_user,
        picked_shipment_ids=payload.picked_shipment_ids if payload else None,
        pickup_otp=payload.pickup_otp if payload else None,
        pickup_otp_override_reason=payload.pickup_otp_override_reason if payload else None,
        **dispatch_kwargs,
    )
    body = ManifestResponse.model_validate(result)
    await idem.store(body)
    return body


@router.get("/{manifest_id}/labels")
async def download_manifest_labels(
    *,
    manifest_id: uuid.UUID,
    label_format: str = Query(
        "a4",
        pattern=LABEL_FORMAT_PATTERN,
        description="a4 (standard labels / LR dockets) or thermal_4x2 (compact box labels)",
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    One merged PDF with the shipping labels of every shipment in the Pickup Request ("Print label").
    """
    service = ManifestService(session)
    manifest, shipments = await service.get_shipments_for_labels(
        manifest_id, current_tenant.id, current_user=current_user
    )
    pdf_buffer = LabelGenerator.generate_batch_pdf(
        shipments, current_tenant, label_format=label_format
    )
    pur_ref = manifest.pickup_request_number or str(manifest.id)[:8].upper()
    suffix = "_Thermal4x2" if label_format == THERMAL_4X2_FORMAT else ""
    filename = f"PUR_{pur_ref}_Labels{suffix}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/{manifest_id}/pdf")
async def download_manifest_runsheet_pdf(
    *,
    manifest_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    session: AsyncSession = Depends(get_session),
):
    """
    Generates a printable A4 Driver Run-Sheet PDF ("Manifest Copy") for the specified Pickup Request.
    """
    service = ManifestService(session)
    manifest, pickup_addr, shipments = await service.get_manifest_with_details(
        manifest_id=manifest_id, tenant_id=current_tenant.id, current_user=current_user
    )
    pdf_buffer = ReceiptPdfGenerator.generate_manifest_runsheet_pdf(
        manifest=manifest,
        tenant=current_tenant,
        pickup_address=pickup_addr,
        shipments=shipments,
    )
    filename = f"Manifest_RunSheet_{str(manifest.id)[:8].upper()}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
