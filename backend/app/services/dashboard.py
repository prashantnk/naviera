import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.manifests import ServiceFlow
from app.models.pickups import NdrExceptionReason, PickupStatus
from app.models.tenants import User, UserRole
from app.services.shipment_lifecycle import ShipmentLifecycleMachine
from app.repositories.dashboard import (
    DashboardRepository,
    ShipmentScope,
    TransitionTimestamps,
)
from app.schemas.v1.dashboard import (
    DASHBOARD_ALLOWED_DAYS,
    B2BStageSummary,
    B2CStageSummary,
    DashboardAppointments,
    DashboardDailyPoint,
    DashboardPerformance,
    DashboardSummaryResponse,
)

PERCENT_MULTIPLIER = 100.0
METRIC_DECIMALS = 1
SECONDS_PER_DAY = 86_400.0
APPOINTMENT_AT_RISK_WINDOW = timedelta(hours=24)
IST_OFFSET = timedelta(hours=5, minutes=30)
IST_TIMEZONE = timezone(IST_OFFSET, name="IST")

# Shipment statuses feeding each stage / series bucket.
RTO_STATUSES = tuple(ShipmentLifecycleMachine.RTO_STATUSES)
DAILY_SERIES_STATUSES: Dict[str, Tuple[PickupStatus, ...]] = {
    "in_transit": (PickupStatus.IN_TRANSIT,),
    "delivered": (PickupStatus.COMPLETED,),
    "returned": RTO_STATUSES,
}

StatusCounts = Dict[Tuple[PickupStatus, Optional[NdrExceptionReason]], int]


class DashboardService:
    """
    Builds the home dashboard summary for one flow (B2C Domestic or B2B Surface).
    All numbers are computed here (Zero Frontend Math).
    Spring Boot Equivalent: '@Service class DashboardService'.
    """

    def __init__(self, session: AsyncSession):
        self.repo = DashboardRepository(session)

    # ----------------------------- pure helpers -----------------------------

    @staticmethod
    def _validate_days(days: int) -> None:
        if days not in DASHBOARD_ALLOWED_DAYS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"days must be one of {list(DASHBOARD_ALLOWED_DAYS)}.",
            )

    @staticmethod
    def _round(value: float) -> float:
        return round(value, METRIC_DECIMALS)

    @classmethod
    def _percent(cls, numerator: int, denominator: int) -> Optional[float]:
        """numerator / denominator as a 0-100 percentage; None when the denominator is zero."""
        if denominator <= 0:
            return None
        return cls._round(numerator / denominator * PERCENT_MULTIPLIER)

    @staticmethod
    def _count(counts: StatusCounts, *statuses: PickupStatus) -> int:
        """Total shipments across the given statuses (any NDR reason)."""
        return sum(n for (s, _), n in counts.items() if s in statuses)

    @staticmethod
    def _count_reason(
        counts: StatusCounts, shipment_status: PickupStatus, reason: NdrExceptionReason
    ) -> int:
        return counts.get((shipment_status, reason), 0)

    @classmethod
    def _b2c_stages(cls, counts: StatusCounts) -> B2CStageSummary:
        return B2CStageSummary(
            to_be_shipped=cls._count(counts, PickupStatus.OPEN),
            awaiting_pickup=cls._count(counts, PickupStatus.ASSIGNED),
            in_transit=cls._count(counts, PickupStatus.IN_TRANSIT),
            out_for_delivery=cls._count(counts, PickupStatus.OUT_FOR_DELIVERY),
            ndr_exceptions=cls._count(counts, PickupStatus.EXCEPTION),
            delivered=cls._count(counts, PickupStatus.COMPLETED),
            rto=cls._count(counts, *RTO_STATUSES),
        )

    @classmethod
    def _b2b_stages(cls, counts: StatusCounts) -> B2BStageSummary:
        return B2BStageSummary(
            lrs_manifested=cls._count(counts, PickupStatus.OPEN, PickupStatus.ASSIGNED),
            in_transit=cls._count(counts, PickupStatus.IN_TRANSIT),
            out_for_delivery=cls._count(counts, PickupStatus.OUT_FOR_DELIVERY),
            exceptions=cls._count(counts, PickupStatus.EXCEPTION),
            consignee_unreachable=cls._count_reason(
                counts, PickupStatus.EXCEPTION, NdrExceptionReason.CUSTOMER_UNAVAILABLE
            ),
            delivered=cls._count(counts, PickupStatus.COMPLETED),
            rto=cls._count(counts, *RTO_STATUSES),
        )

    @staticmethod
    def _had_exception_before_delivery(ts: TransitionTimestamps) -> bool:
        """True when an EXCEPTION was logged before (or without) the first COMPLETED event."""
        if ts.first_exception is None:
            return False
        return ts.first_completed is None or ts.first_exception < ts.first_completed

    @classmethod
    def _first_attempt_rate(
        cls, delivered: int, timestamps: List[TransitionTimestamps]
    ) -> Optional[float]:
        """Delivered shipments without a prior EXCEPTION / all delivered shipments."""
        failed_first = sum(
            1
            for ts in timestamps
            if ts.current_status == PickupStatus.COMPLETED
            and cls._had_exception_before_delivery(ts)
        )
        return cls._percent(delivered - failed_first, delivered)

    @classmethod
    def _avg_days_to_first_attempt(cls, timestamps: List[TransitionTimestamps]) -> Optional[float]:
        """Mean days between first IN_TRANSIT and first COMPLETED/EXCEPTION event."""
        durations = [
            (ts.first_attempt - ts.first_in_transit).total_seconds() / SECONDS_PER_DAY
            for ts in timestamps
            if ts.first_in_transit is not None
            and ts.first_attempt is not None
            and ts.first_attempt >= ts.first_in_transit
        ]
        if not durations:
            return None
        return cls._round(sum(durations) / len(durations))

    @staticmethod
    def _window_dates(today: date, days: int) -> List[date]:
        """Every calendar day in the window, oldest first (inclusive of today)."""
        return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]

    @classmethod
    def _ist_window_and_utc_cutoff(
        cls, now_utc: datetime, days: int
    ) -> Tuple[List[date], datetime]:
        """
        Computes the `days`-day calendar window in IST (`Asia/Kolkata`, UTC+05:30)
        and the naive UTC timestamp corresponding to 00:00:00 IST on `window[0]`.
        """
        today_ist = now_utc.astimezone(IST_TIMEZONE).date()
        window = cls._window_dates(today_ist, days)
        since_utc_naive = datetime.combine(window[0], datetime.min.time()) - IST_OFFSET
        return window, since_utc_naive

    @staticmethod
    def _daily_series(
        window: List[date], transitions: Dict[Tuple[date, str], int]
    ) -> List[DashboardDailyPoint]:
        """Zero-filled per-day series of shipments entering in-transit / delivered / returned."""

        def bucket_total(day: date, bucket: str) -> int:
            return sum(transitions.get((day, s.value), 0) for s in DAILY_SERIES_STATUSES[bucket])

        return [
            DashboardDailyPoint(
                date=day,
                in_transit=bucket_total(day, "in_transit"),
                delivered=bucket_total(day, "delivered"),
                returned=bucket_total(day, "returned"),
            )
            for day in window
        ]

    @staticmethod
    def _build_scope(
        tenant_id: uuid.UUID, service_flow: ServiceFlow, since: datetime, user: User
    ) -> ShipmentScope:
        """Customers only see their own shipments; Admin/Owner see the whole tenant."""
        return ShipmentScope(
            tenant_id=tenant_id,
            is_b2b=service_flow == ServiceFlow.B2B,
            created_since=since,
            created_by_user_id=user.id if user.role == UserRole.customer else None,
        )

    # ------------------------------- use case -------------------------------

    async def get_summary(
        self,
        tenant_id: uuid.UUID,
        current_user: User,
        service_flow: ServiceFlow,
        days: int,
    ) -> DashboardSummaryResponse:
        """Aggregates stages, performance, daily series and (B2B) appointments for the window."""
        self._validate_days(days)
        now = datetime.now(timezone.utc)
        # Bucket daily series in IST (Asia/Kolkata, UTC+05:30) while comparing
        # PickupRequest.created_at / ShipmentActivity.timestamp in naive UTC (F-02).
        window, since = self._ist_window_and_utc_cutoff(now, days)
        scope = self._build_scope(tenant_id, service_flow, since, current_user)

        series_statuses = [s for group in DAILY_SERIES_STATUSES.values() for s in group]
        aggregates = await self.repo.load_summary_aggregates(scope, series_statuses)
        counts, timestamps, transitions = (
            aggregates.counts,
            aggregates.timestamps,
            aggregates.transitions,
        )

        delivered = self._count(counts, PickupStatus.COMPLETED)
        rto = self._count(counts, *RTO_STATUSES)
        performance = DashboardPerformance(
            successful_delivery_rate=self._percent(delivered, delivered + rto),
            first_attempt_delivery_rate=self._first_attempt_rate(delivered, timestamps),
            avg_days_to_first_attempt=self._avg_days_to_first_attempt(timestamps),
            on_time_delivery_rate=None,  # no promised/estimated delivery date or TAT is stored
        )

        appointments: Optional[DashboardAppointments] = None
        if service_flow == ServiceFlow.B2B:
            appt = await self.repo.appointment_counts(
                scope, now=now, at_risk_until=now + APPOINTMENT_AT_RISK_WINDOW
            )
            appointments = DashboardAppointments(
                needed=appt.needed, at_risk=appt.at_risk, booked=appt.booked
            )

        stages = (
            self._b2b_stages(counts)
            if service_flow == ServiceFlow.B2B
            else self._b2c_stages(counts)
        )
        return DashboardSummaryResponse(
            service_flow=service_flow,
            days=days,
            generated_at=now,
            stages=stages,
            performance=performance,
            daily_series=self._daily_series(window, transitions),
            appointments=appointments,
        )
