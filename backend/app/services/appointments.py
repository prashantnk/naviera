"""
Business rules for the B2B "Manage Appointments" page.

Scoping: Tenant Staff see every B2B LR of the tenant; customers see only the
LRs they created. Booking itself stays on the existing
`PATCH /api/v1/shipments/{id}/appointment` (`ShipmentService.update_appointment`).

Spring Boot Equivalent: a read-only '@Service' orchestrating one repository.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.permissions import is_tenant_staff
from app.models.pickups import PickupRequest
from app.models.tenants import User
from app.repositories.appointments import (
    AppointmentFilters,
    AppointmentScope,
    AppointmentsRepository,
)
from app.schemas.v1.appointments import (
    AppointmentListResponse,
    AppointmentRow,
    AppointmentTab,
    AppointmentTabCounts,
)

APPOINTMENT_AT_RISK_WINDOW = timedelta(hours=24)
"""Same window as the dashboard "at risk" counter (`services/dashboard.py`)."""


class AppointmentsService:
    """Lists B2B LRs per appointment tab with Delhivery-style PO flags."""

    def __init__(self, repo: AppointmentsRepository):
        self.repo = repo

    @staticmethod
    def _build_scope(tenant_id: uuid.UUID, user: User, now: datetime) -> AppointmentScope:
        """Staff: whole tenant. Customers: their own LRs only."""
        return AppointmentScope(
            tenant_id=tenant_id,
            created_by_user_id=None if is_tenant_staff(user) else user.id,
            now=now,
            at_risk_until=now + APPOINTMENT_AT_RISK_WINDOW,
            today=now.date(),
        )

    @staticmethod
    def _box_count(shipment: PickupRequest) -> int:
        """Blind pickups declare a box count; otherwise sum the package box counts."""
        if shipment.is_blind_pickup:
            return shipment.estimated_box_count or 0
        return sum(pkg.box_count for pkg in shipment.packages or [])

    @staticmethod
    def _is_po_missing(shipment: PickupRequest) -> bool:
        """No PO number recorded yet."""
        return not (shipment.po_number or "").strip()

    @staticmethod
    def _is_po_expired(shipment: PickupRequest, today: date) -> bool:
        """PO expiry date is before today."""
        return shipment.po_expiry_date is not None and shipment.po_expiry_date < today

    @staticmethod
    def _delivery_by(shipment: PickupRequest) -> Optional[date]:
        """No PDD/TAT is stored, so the booked slot date is the delivery date when present."""
        start = shipment.appointment_start
        return start.date() if start is not None else None

    @classmethod
    def _to_row(cls, shipment: PickupRequest, today: date) -> AppointmentRow:
        """Map an ORM shipment to the table row DTO."""
        consignee = shipment.delivery_address
        return AppointmentRow(
            shipment_id=shipment.id,
            tracking_id=shipment.tracking_id,
            order_reference_id=shipment.order_reference_id,
            box_count=cls._box_count(shipment),
            consignee_name=consignee.name if consignee else None,
            consignee_company=consignee.company_name if consignee else None,
            consignee_city=consignee.city if consignee else None,
            consignee_pincode=consignee.pincode if consignee else None,
            po_number=shipment.po_number,
            po_expiry_date=shipment.po_expiry_date,
            po_missing=cls._is_po_missing(shipment),
            po_expired=cls._is_po_expired(shipment, today),
            status=shipment.status,
            ndr_reason=shipment.ndr_reason,
            delivery_by=cls._delivery_by(shipment),
            appointment_start=shipment.appointment_start,
            appointment_end=shipment.appointment_end,
            appointment_id=shipment.appointment_id,
        )

    async def list_appointments(
        self,
        *,
        tenant_id: uuid.UUID,
        user: User,
        tab: AppointmentTab,
        filters: AppointmentFilters,
        page: int,
        size: int,
        now: Optional[datetime] = None,
    ) -> AppointmentListResponse:
        """
        One page of the selected tab plus the three tab counts.

        Args:
            tenant_id: Tenant isolation key.
            user: Caller (customers are restricted to their own LRs).
            tab: pending / at_risk / booked.
            filters: Optional search / consignee / city / status / date / PO filters.
            page: 1-based page number.
            size: Page size.
            now: Clock override for tests (defaults to current UTC time).
        """
        clock = now or datetime.now(timezone.utc)
        scope = self._build_scope(tenant_id, user, clock)
        counts = await self.repo.tab_counts(scope)
        shipments, total = await self.repo.list_tab(
            scope=scope,
            tab=tab,
            filters=filters,
            offset=(page - 1) * size,
            limit=size,
        )
        return AppointmentListResponse(
            tab=tab,
            items=[self._to_row(shipment, scope.today) for shipment in shipments],
            total=total,
            page=page,
            size=size,
            counts=AppointmentTabCounts(
                pending=counts.pending, at_risk=counts.at_risk, booked=counts.booked
            ),
        )


def get_appointments_service(
    session: AsyncSession = Depends(get_session),
) -> AppointmentsService:
    """FastAPI factory wiring the repository on the request session."""
    return AppointmentsService(AppointmentsRepository(session))
