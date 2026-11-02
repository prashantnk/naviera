"""
B2B "Manage Appointments" API (Delhivery One parity).
Thin controller: query validation + dependency injection only; rules live in
`AppointmentsService`, SQL in `AppointmentsRepository`. Booking a slot uses the
existing `PATCH /api/v1/shipments/{id}/appointment`.
Spring Boot Equivalent: '@RestController @RequestMapping("/api/v1/appointments")'.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.pickups import PickupStatus
from app.models.tenants import Tenant, User
from app.repositories.appointments import AppointmentFilters
from app.schemas.v1.appointments import (
    APPOINTMENTS_DEFAULT_PAGE_SIZE,
    APPOINTMENTS_MAX_PAGE_SIZE,
    AppointmentListResponse,
    AppointmentTab,
)
from app.services.appointments import AppointmentsService, get_appointments_service

MAX_FILTER_LENGTH = 100

router = APIRouter()


@router.get("", response_model=AppointmentListResponse)
async def list_appointments(
    *,
    tab: AppointmentTab = Query(..., description="pending, at_risk or booked"),
    search: Optional[str] = Query(
        default=None, max_length=MAX_FILTER_LENGTH, description="LRN / Order ID / PO number"
    ),
    consignee: Optional[str] = Query(default=None, max_length=MAX_FILTER_LENGTH),
    city: Optional[str] = Query(default=None, max_length=MAX_FILTER_LENGTH),
    status: Optional[PickupStatus] = Query(default=None),
    pdd_from: Optional[date] = Query(default=None, description="Delivery-by date from"),
    pdd_to: Optional[date] = Query(default=None, description="Delivery-by date to"),
    expired_po_only: bool = Query(default=False),
    page: int = Query(1, ge=1),
    size: int = Query(APPOINTMENTS_DEFAULT_PAGE_SIZE, ge=1, le=APPOINTMENTS_MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    service: AppointmentsService = Depends(get_appointments_service),
):
    """B2B LRs per appointment tab (tenant-wide for staff, own LRs for customers) + tab counts."""
    return await service.list_appointments(
        tenant_id=current_tenant.id,
        user=current_user,
        tab=tab,
        filters=AppointmentFilters(
            search=search,
            consignee=consignee,
            city=city,
            status=status,
            delivery_from=pdd_from,
            delivery_to=pdd_to,
            expired_po_only=expired_po_only,
        ),
        page=page,
        size=size,
    )
