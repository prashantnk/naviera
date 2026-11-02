"""
Data access for the B2B "Manage Appointments" page.

Tab predicates mirror `DashboardRepository.appointment_counts` (needed / at risk /
booked) so the dashboard counters and this page always agree. Every query is
tenant-scoped, restricted to B2B cargo via the shared `b2b_shipment_clause()`,
and restricted to the creator for customers.

Spring Boot Equivalent: a '@Repository' with JPA Specifications per tab.
"""

import uuid
from datetime import date, datetime
from typing import Any, List, NamedTuple, Optional

from sqlalchemy import Date, ColumnElement, and_, cast, desc, nulls_last, or_
from sqlalchemy.orm import joinedload, selectinload
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pickups import Address, NdrExceptionReason, PickupRequest, PickupStatus
from app.repositories.dashboard import ACTIVE_APPOINTMENT_STATUSES
from app.repositories.shipments import b2b_shipment_clause
from app.schemas.v1.appointments import AppointmentTab


class AppointmentScope(NamedTuple):
    """Who the page lists for: tenant, optional creator (customers), clock."""

    tenant_id: uuid.UUID
    created_by_user_id: Optional[uuid.UUID]
    now: datetime
    at_risk_until: datetime
    today: date


class AppointmentFilters(NamedTuple):
    """Optional list filters (all combined with AND)."""

    search: Optional[str] = None
    consignee: Optional[str] = None
    city: Optional[str] = None
    status: Optional[PickupStatus] = None
    delivery_from: Optional[date] = None
    delivery_to: Optional[date] = None
    expired_po_only: bool = False


class AppointmentCountsRow(NamedTuple):
    pending: int
    at_risk: int
    booked: int


def _has_appointment_id() -> ColumnElement[bool]:
    """Appointment id present and non-empty."""
    return and_(
        col(PickupRequest.appointment_id).is_not(None),
        col(PickupRequest.appointment_id) != "",
    )


def _is_active() -> ColumnElement[bool]:
    """Shipment still in a state where an appointment is actionable."""
    return col(PickupRequest.status).in_(ACTIVE_APPOINTMENT_STATUSES)


def pending_clause() -> ColumnElement[bool]:
    """Dashboard "needed": on hold for APPOINTMENT_NEEDED, or appointment id without a slot."""
    return or_(
        and_(
            col(PickupRequest.status) == PickupStatus.EXCEPTION,
            col(PickupRequest.ndr_reason) == NdrExceptionReason.APPOINTMENT_NEEDED,
        ),
        and_(_has_appointment_id(), col(PickupRequest.appointment_start).is_(None), _is_active()),
    )


def at_risk_clause(now: datetime, at_risk_until: datetime) -> ColumnElement[bool]:
    """Dashboard "at risk": active and the booked slot starts within the risk window."""
    start = col(PickupRequest.appointment_start)
    return and_(_is_active(), start >= now, start <= at_risk_until)


def booked_clause(now: datetime) -> ColumnElement[bool]:
    """Dashboard "booked": active with an upcoming booked slot."""
    return and_(_is_active(), col(PickupRequest.appointment_start) >= now)


def _tab_clause(tab: AppointmentTab, scope: AppointmentScope) -> ColumnElement[bool]:
    """WHERE clause for one tab."""
    if tab == AppointmentTab.at_risk:
        return at_risk_clause(scope.now, scope.at_risk_until)
    if tab == AppointmentTab.booked:
        return booked_clause(scope.now)
    return pending_clause()


def _scope_filters(scope: AppointmentScope) -> List[ColumnElement[bool]]:
    """Tenant + B2B cargo (+ creator for customers)."""
    filters: List[ColumnElement[bool]] = [
        col(PickupRequest.tenant_id) == scope.tenant_id,
        b2b_shipment_clause(),
    ]
    if scope.created_by_user_id is not None:
        filters.append(col(PickupRequest.created_by_user_id) == scope.created_by_user_id)
    return filters


def _delivery_address_exists(*conditions: ColumnElement[bool]) -> ColumnElement[bool]:
    """Correlated EXISTS on the shipment's delivery (consignee) address."""
    return (
        select(Address.id)
        .where(Address.id == PickupRequest.delivery_address_id, *conditions)
        .exists()
    )


def _filter_clauses(
    filters: AppointmentFilters, today: date
) -> List[ColumnElement[bool]]:
    """Translate the optional UI filters into WHERE clauses."""
    clauses: List[ColumnElement[bool]] = []
    term = (filters.search or "").strip()
    if term:
        clauses.append(
            or_(
                col(PickupRequest.tracking_id).icontains(term, autoescape=True),
                col(PickupRequest.order_reference_id).icontains(term, autoescape=True),
                col(PickupRequest.po_number).icontains(term, autoescape=True),
            )
        )
    consignee = (filters.consignee or "").strip()
    if consignee:
        clauses.append(
            _delivery_address_exists(
                or_(
                    col(Address.name).icontains(consignee, autoescape=True),
                    col(Address.company_name).icontains(consignee, autoescape=True),
                )
            )
        )
    city = (filters.city or "").strip()
    if city:
        clauses.append(_delivery_address_exists(col(Address.city).icontains(city, autoescape=True)))
    if filters.status is not None:
        clauses.append(col(PickupRequest.status) == filters.status)
    appointment_day = cast(col(PickupRequest.appointment_start), Date)
    if filters.delivery_from is not None:
        clauses.append(appointment_day >= filters.delivery_from)
    if filters.delivery_to is not None:
        clauses.append(appointment_day <= filters.delivery_to)
    if filters.expired_po_only:
        clauses.append(col(PickupRequest.po_expiry_date) < today)
    return clauses


def _row_load_options() -> List[Any]:
    """Eager-load what a row needs (no MissingGreenlet during serialisation)."""
    return [
        joinedload(PickupRequest.delivery_address),  # type: ignore[arg-type]
        selectinload(PickupRequest.packages),  # type: ignore[arg-type]
    ]


class AppointmentsRepository:
    """Read-only queries behind `GET /api/v1/appointments`."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def tab_counts(self, scope: AppointmentScope) -> AppointmentCountsRow:
        """Pending / at risk / booked counts in one round trip (scope only)."""
        statement = select(
            func.count().filter(pending_clause()),
            func.count().filter(at_risk_clause(scope.now, scope.at_risk_until)),
            func.count().filter(booked_clause(scope.now)),
        ).where(*_scope_filters(scope))
        row = (await self.session.exec(statement)).one()
        return AppointmentCountsRow(int(row[0]), int(row[1]), int(row[2]))

    async def list_tab(
        self,
        *,
        scope: AppointmentScope,
        tab: AppointmentTab,
        filters: AppointmentFilters,
        offset: int,
        limit: int,
    ) -> tuple[List[PickupRequest], int]:
        """
        One page of shipments for a tab plus the filtered total.

        Ordering: booked tabs by soonest slot; pending by newest shipment.
        """
        where = _scope_filters(scope) + [_tab_clause(tab, scope)] + _filter_clauses(
            filters, scope.today
        )
        total = (
            await self.session.exec(select(func.count()).select_from(PickupRequest).where(*where))
        ).one()
        if tab == AppointmentTab.pending:
            order = [desc(col(PickupRequest.created_at))]
        else:
            order = [nulls_last(col(PickupRequest.appointment_start).asc())]
        statement = (
            select(PickupRequest)
            .where(*where)
            .order_by(*order)
            .offset(offset)
            .limit(limit)
            .options(*_row_load_options())
        )
        rows = (await self.session.exec(statement)).unique().all()
        return list(rows), int(total)
