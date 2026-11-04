"""
Delivery Exceptions / NDR API (Delhivery One "Exceptions & NDR").
Thin controllers: validation + dependency injection only; rules live in
`ExceptionsService` / `ndr_rules`, SQL in `ExceptionsRepository`.
Spring Boot Equivalent: '@RestController @RequestMapping("/api/v1/exceptions")'.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.core.idempotency import IdempotencyContext, require_idempotency
from app.models.exceptions import ExceptionCategory
from app.models.manifests import ServiceFlow
from app.models.tenants import Tenant, User
from app.schemas.v1.exceptions import (
    EXCEPTIONS_DEFAULT_PAGE_SIZE,
    EXCEPTIONS_MAX_PAGE_SIZE,
    BulkNdrActionRequest,
    BulkNdrActionResponse,
    ExceptionListResponse,
    ExceptionRow,
    ExceptionSummaryResponse,
    NdrActionRequest,
)
from app.services.exceptions import ExceptionsService, get_exceptions_service

MAX_SEARCH_LENGTH = 100
IDEMPOTENCY_EXCEPTION_ACTION = "exceptions.actions"
IDEMPOTENCY_EXCEPTION_BULK_ACTION = "exceptions.bulk_action"

router = APIRouter()


@router.get("/summary", response_model=ExceptionSummaryResponse)
async def get_exceptions_summary(
    *,
    service_flow: ServiceFlow = Query(..., description="B2C (Domestic) or B2B (Cargo)"),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: ExceptionsService = Depends(get_exceptions_service),
):
    """Live counts per group (B2C) / category (B2B), actionable vs non-actionable."""
    return await service.get_summary(
        tenant_id=current_tenant.id, user=current_user, service_flow=service_flow
    )


@router.get("", response_model=ExceptionListResponse)
async def list_exceptions(
    *,
    service_flow: ServiceFlow = Query(..., description="B2C (Domestic) or B2B (Cargo)"),
    category: Optional[ExceptionCategory] = Query(default=None),
    actionable_only: bool = Query(default=False),
    search: Optional[str] = Query(
        default=None, max_length=MAX_SEARCH_LENGTH, description="AWB / LRN or Order ID"
    ),
    page: int = Query(1, ge=1),
    size: int = Query(EXCEPTIONS_DEFAULT_PAGE_SIZE, ge=1, le=EXCEPTIONS_MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: ExceptionsService = Depends(get_exceptions_service),
):
    """On-hold shipments with allowed actions, attempts, last remark and server-side aging."""
    return await service.list_exceptions(
        tenant_id=current_tenant.id,
        user=current_user,
        service_flow=service_flow,
        category=category,
        actionable_only=actionable_only,
        search=search,
        page=page,
        size=size,
        tenant=current_tenant,
    )


@router.post("/bulk-action", response_model=BulkNdrActionResponse)
async def apply_bulk_exception_action(
    *,
    payload: BulkNdrActionRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: ExceptionsService = Depends(get_exceptions_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_EXCEPTION_BULK_ACTION)),
):
    """Bulk REATTEMPT / RETURN_TO_ORIGIN / RESCHEDULE_PICKUP / CANCEL_PICKUP (max 200, partial success)."""
    if idem.replay is not None:
        return idem.replay
    body = await service.apply_bulk_action(
        request=payload, user=current_user, tenant=current_tenant
    )
    await idem.store(body)
    return body


@router.post("/{shipment_id}/actions", response_model=ExceptionRow)
async def apply_exception_action(
    *,
    shipment_id: uuid.UUID,
    payload: NdrActionRequest,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: ExceptionsService = Depends(get_exceptions_service),
    idem: IdempotencyContext = Depends(require_idempotency(IDEMPOTENCY_EXCEPTION_ACTION)),
):
    """Apply one merchant action (validated against the allowed-actions matrix)."""
    if idem.replay is not None:
        return idem.replay
    body = await service.apply_action(
        shipment_id=shipment_id,
        request=payload,
        user=current_user,
        tenant=current_tenant,
    )
    await idem.store(body)
    return body
