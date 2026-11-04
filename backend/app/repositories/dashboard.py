import uuid
from datetime import date, datetime
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy import ColumnElement, and_, distinct, or_
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pickups import (
    ActivityType,
    NdrExceptionReason,
    PickupRequest,
    PickupStatus,
    ShipmentActivity,
)
from app.repositories.shipments import b2b_shipment_clause

# Shipment states in which a delivery appointment is still actionable.
ACTIVE_APPOINTMENT_STATUSES = (
    PickupStatus.DRAFT,
    PickupStatus.OPEN,
    PickupStatus.ASSIGNED,
    PickupStatus.IN_TRANSIT,
    PickupStatus.EXCEPTION,
)

# Naive UTC `ShipmentActivity.timestamp` shifted to IST (Asia/Kolkata, UTC+05:30)
# before extracting the calendar date for `daily_series` buckets (F-02).
IST_SQL_OFFSET = sa.text("INTERVAL '5 hours 30 minutes'")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """ISO timestamp from json_agg output (naive UTC) -> datetime."""
    return datetime.fromisoformat(value) if value else None


class ShipmentScope(NamedTuple):
    """Who/what the dashboard aggregates over (tenant, flow, window, optional customer)."""

    tenant_id: uuid.UUID
    is_b2b: bool
    created_since: datetime
    created_by_user_id: Optional[uuid.UUID] = None


class TransitionTimestamps(NamedTuple):
    """First time a shipment entered key states (from the ShipmentActivity ledger)."""

    pickup_id: uuid.UUID
    current_status: PickupStatus
    first_in_transit: Optional[datetime]
    first_attempt: Optional[datetime]
    first_exception: Optional[datetime]
    first_completed: Optional[datetime]


class AppointmentCounts(NamedTuple):
    needed: int
    at_risk: int
    booked: int


class DashboardAggregates(NamedTuple):
    """The three (or four for B2B) aggregate result sets loaded in one round trip."""

    counts: Dict[Tuple[PickupStatus, Optional[NdrExceptionReason]], int]
    timestamps: List[TransitionTimestamps]
    transitions: Dict[Tuple[date, str], int]
    appointments: Optional[AppointmentCounts] = None


class DashboardRepository:
    """
    Read-only aggregate queries for the home dashboard. Every query is tenant-scoped,
    flow-scoped (shared B2B classifier) and optionally customer-scoped.
    Spring Boot Equivalent: a '@Repository' with '@Query' aggregate projections.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _scope_filters(scope: ShipmentScope) -> List[ColumnElement[bool]]:
        """WHERE clauses shared by every dashboard query."""
        flow_clause = b2b_shipment_clause()
        filters: List[ColumnElement[bool]] = [
            PickupRequest.tenant_id == scope.tenant_id,
            col(PickupRequest.created_at) >= scope.created_since,
            flow_clause if scope.is_b2b else ~flow_clause,
        ]
        if scope.created_by_user_id is not None:
            filters.append(PickupRequest.created_by_user_id == scope.created_by_user_id)
        return filters

    @staticmethod
    def _activity_new_status() -> ColumnElement[str]:
        """'diff -> status ->> new' — the status a ShipmentActivity transitioned INTO."""
        return ShipmentActivity.diff["status"]["new"].as_string()  # type: ignore[index]

    @staticmethod
    def _json_rows(*columns: Any) -> Any:
        """`json_agg(json_build_array(...))`, decoded to a Python list by SQLAlchemy."""
        return func.json_agg(func.json_build_array(*columns), type_=sa.JSON)

    async def load_summary_aggregates(
        self,
        scope: ShipmentScope,
        statuses: List[PickupStatus],
        appointment_window: Optional[Tuple[datetime, datetime]] = None,
    ) -> DashboardAggregates:
        """
        Status/reason counts, per-shipment first-transition timestamps, the
        per-day transition series, and (when `appointment_window` is provided)
        B2B appointment counts in ONE round trip.

        CTEs: `scoped` (shipments in scope) -> `status_counts`; `acts` (their
        activity ledger) -> `firsts` and `daily`. Each CTE is folded into a
        `json_agg` scalar so the result sets travel in a single row.
        """
        if appointment_window is not None:
            scoped = (
                select(
                    PickupRequest.id,
                    PickupRequest.status,
                    PickupRequest.ndr_reason,
                    PickupRequest.appointment_id,
                    PickupRequest.appointment_start,
                )
                .where(*self._scope_filters(scope))
                .cte("scoped")
            )
        else:
            scoped = (
                select(PickupRequest.id, PickupRequest.status, PickupRequest.ndr_reason)
                .where(*self._scope_filters(scope))
                .cte("scoped")
            )
        status_counts = (
            select(scoped.c.status, scoped.c.ndr_reason, func.count().label("n"))
            .group_by(scoped.c.status, scoped.c.ndr_reason)
            .cte("status_counts")
        )
        acts = (
            select(
                ShipmentActivity.pickup_id,
                ShipmentActivity.timestamp,
                ShipmentActivity.activity_type,
                self._activity_new_status().label("new_status"),
            )
            .join(scoped, scoped.c.id == col(ShipmentActivity.pickup_id))
            .cte("acts")
        )
        is_exception = or_(
            acts.c.new_status == PickupStatus.EXCEPTION.value,
            acts.c.activity_type == ActivityType.EXCEPTION,
        )
        is_completed = acts.c.new_status == PickupStatus.COMPLETED.value
        firsts = (
            select(
                acts.c.pickup_id,
                scoped.c.status,
                func.min(acts.c.timestamp)
                .filter(acts.c.new_status == PickupStatus.IN_TRANSIT.value)
                .label("first_in_transit"),
                func.min(acts.c.timestamp)
                .filter(or_(is_completed, is_exception))
                .label("first_attempt"),
                func.min(acts.c.timestamp).filter(is_exception).label("first_exception"),
                func.min(acts.c.timestamp).filter(is_completed).label("first_completed"),
            )
            .join(scoped, scoped.c.id == acts.c.pickup_id)
            .group_by(acts.c.pickup_id, scoped.c.status)
            .cte("firsts")
        )
        day = func.date(acts.c.timestamp + IST_SQL_OFFSET).label("day")
        daily = (
            select(day, acts.c.new_status, func.count(distinct(acts.c.pickup_id)).label("n"))
            .where(
                acts.c.timestamp >= scope.created_since,
                acts.c.new_status.in_([s.value for s in statuses]),
            )
            .group_by(day, acts.c.new_status)
            .cte("daily")
        )
        counts_subq = select(
            self._json_rows(status_counts.c.status, status_counts.c.ndr_reason, status_counts.c.n)
        ).scalar_subquery()
        firsts_subq = select(
            self._json_rows(
                firsts.c.pickup_id,
                firsts.c.status,
                firsts.c.first_in_transit,
                firsts.c.first_attempt,
                firsts.c.first_exception,
                firsts.c.first_completed,
            )
        ).scalar_subquery()
        daily_subq = select(
            self._json_rows(daily.c.day, daily.c.new_status, daily.c.n)
        ).scalar_subquery()

        appointments_result: Optional[AppointmentCounts] = None
        if appointment_window is not None:
            now_ts, at_risk_until = appointment_window
            is_active = scoped.c.status.in_(ACTIVE_APPOINTMENT_STATUSES)
            start = scoped.c.appointment_start
            has_appointment_id = and_(
                scoped.c.appointment_id.is_not(None),
                scoped.c.appointment_id != "",
            )
            needed = or_(
                and_(
                    scoped.c.status == PickupStatus.EXCEPTION,
                    scoped.c.ndr_reason == NdrExceptionReason.APPOINTMENT_NEEDED,
                ),
                and_(has_appointment_id, start.is_(None), is_active),
            )
            at_risk = and_(is_active, start >= now_ts, start <= at_risk_until)
            booked = and_(is_active, start >= now_ts)
            appt_subq = (
                select(
                    func.json_build_array(
                        func.count().filter(needed),
                        func.count().filter(at_risk),
                        func.count().filter(booked),
                        type_=sa.JSON,
                    )
                )
                .select_from(scoped)
                .scalar_subquery()
            )
            statement = select(counts_subq, firsts_subq, daily_subq, appt_subq)
            counts_json, firsts_json, daily_json, appt_json = (
                await self.session.exec(statement)
            ).one()
            if appt_json and len(appt_json) >= 3:
                appointments_result = AppointmentCounts(
                    int(appt_json[0] or 0),
                    int(appt_json[1] or 0),
                    int(appt_json[2] or 0),
                )
            else:
                appointments_result = AppointmentCounts(0, 0, 0)
        else:
            statement = select(counts_subq, firsts_subq, daily_subq)
            counts_json, firsts_json, daily_json = (await self.session.exec(statement)).one()

        return DashboardAggregates(
            counts={
                (PickupStatus(s), NdrExceptionReason(r) if r else None): int(n)
                for s, r, n in counts_json or []
            },
            timestamps=[
                TransitionTimestamps(
                    uuid.UUID(pid),
                    PickupStatus(status),
                    *(_parse_ts(value) for value in stamps),
                )
                for pid, status, *stamps in firsts_json or []
            ],
            transitions={
                (date.fromisoformat(d), new_status): int(n) for d, new_status, n in daily_json or []
            },
            appointments=appointments_result,
        )

    async def appointment_counts(
        self, scope: ShipmentScope, now: datetime, at_risk_until: datetime
    ) -> AppointmentCounts:
        """B2B appointment management counters (needed / at risk / booked)."""
        is_active = col(PickupRequest.status).in_(ACTIVE_APPOINTMENT_STATUSES)
        start = col(PickupRequest.appointment_start)
        has_appointment_id = and_(
            col(PickupRequest.appointment_id).is_not(None),
            col(PickupRequest.appointment_id) != "",
        )
        needed = or_(
            and_(
                PickupRequest.status == PickupStatus.EXCEPTION,
                PickupRequest.ndr_reason == NdrExceptionReason.APPOINTMENT_NEEDED,
            ),
            and_(has_appointment_id, start.is_(None), is_active),
        )
        at_risk = and_(is_active, start >= now, start <= at_risk_until)
        booked = and_(is_active, start >= now)
        query = select(
            func.count().filter(needed),
            func.count().filter(at_risk),
            func.count().filter(booked),
        ).where(*self._scope_filters(scope))
        row = (await self.session.exec(query)).one()
        return AppointmentCounts(int(row[0]), int(row[1]), int(row[2]))
