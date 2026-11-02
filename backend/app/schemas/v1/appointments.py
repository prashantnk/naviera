"""
DTOs for the B2B "Manage Appointments" page (`GET /api/v1/appointments`).
Spring Boot Equivalent: response DTO classes for a read-only list controller.
"""

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from sqlmodel import SQLModel

from app.models.pickups import NdrExceptionReason, PickupStatus

APPOINTMENTS_DEFAULT_PAGE_SIZE = 20
APPOINTMENTS_MAX_PAGE_SIZE = 100


class AppointmentTab(str, Enum):
    """
    Delhivery tabs. Definitions match the B2B dashboard appointment counters
    (`DashboardRepository.appointment_counts`):
    - pending: on hold for APPOINTMENT_NEEDED, or has an appointment id but no slot yet.
    - at_risk: an active shipment whose booked slot starts within the next 24 hours.
    - booked: an active shipment with an upcoming booked slot.
    """

    pending = "pending"
    at_risk = "at_risk"
    booked = "booked"


class AppointmentTabCounts(SQLModel):
    """Live count per tab (same scope as the list, ignoring the other filters)."""

    pending: int
    at_risk: int
    booked: int


class AppointmentRow(SQLModel):
    """One LR on the Manage Appointments table."""

    shipment_id: UUID
    tracking_id: Optional[str] = None
    order_reference_id: Optional[str] = None
    box_count: int
    consignee_name: Optional[str] = None
    consignee_company: Optional[str] = None
    consignee_city: Optional[str] = None
    consignee_pincode: Optional[str] = None
    po_number: Optional[str] = None
    po_expiry_date: Optional[date] = None
    po_missing: bool
    po_expired: bool
    status: PickupStatus
    ndr_reason: Optional[NdrExceptionReason] = None
    # Promised delivery date: Naviera stores no PDD/TAT, so this is the booked
    # appointment date when there is one, otherwise null.
    delivery_by: Optional[date] = None
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    appointment_id: Optional[str] = None


class AppointmentListResponse(SQLModel):
    """Paginated rows for the selected tab plus the three tab counts."""

    tab: AppointmentTab
    items: List[AppointmentRow]
    total: int
    page: int
    size: int
    counts: AppointmentTabCounts
