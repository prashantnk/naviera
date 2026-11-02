from datetime import date, datetime
from typing import List, Optional, Union

from pydantic import BaseModel, Field

from app.models.manifests import ServiceFlow

DASHBOARD_ALLOWED_DAYS = (7, 14, 30)
DASHBOARD_DEFAULT_DAYS = 30


class B2CStageSummary(BaseModel):
    """Delhivery Domestic 'Order summary' stage counters (B2C flow)."""

    to_be_shipped: int = Field(description="OPEN — Ready to Ship")
    awaiting_pickup: int = Field(description="ASSIGNED — linked to a Pickup Request")
    in_transit: int = Field(description="IN_TRANSIT")
    out_for_delivery: int = Field(default=0, description="OUT_FOR_DELIVERY")
    ndr_exceptions: int = Field(description="EXCEPTION (NDR & other exceptions)")
    delivered: int = Field(description="COMPLETED")
    rto: int = Field(description="RTO_INITIATED")


class B2BStageSummary(BaseModel):
    """Delhivery B2B Surface 'Shipment summary' stage counters (B2B flow)."""

    lrs_manifested: int = Field(description="OPEN + ASSIGNED — LRs created, awaiting pickup")
    in_transit: int = Field(description="IN_TRANSIT")
    out_for_delivery: int = Field(default=0, description="OUT_FOR_DELIVERY")
    exceptions: int = Field(description="EXCEPTION (all reasons, incl. appointment & consignee unreachable)")
    consignee_unreachable: int = Field(description="EXCEPTION with ndr_reason CUSTOMER_UNAVAILABLE")
    delivered: int = Field(description="COMPLETED")
    rto: int = Field(description="RTO_INITIATED")


class DashboardPerformance(BaseModel):
    """Percentages are 0-100 rounded to 1 decimal; null when the denominator is zero or data is missing."""

    successful_delivery_rate: Optional[float] = Field(
        default=None, description="delivered / (delivered + rto) x 100"
    )
    first_attempt_delivery_rate: Optional[float] = Field(
        default=None, description="delivered with no EXCEPTION before delivery / delivered x 100"
    )
    avg_days_to_first_attempt: Optional[float] = Field(
        default=None, description="Mean days from first IN_TRANSIT to first COMPLETED/EXCEPTION"
    )
    on_time_delivery_rate: Optional[float] = Field(
        default=None,
        description="Null: shipments carry no promised / estimated delivery date or TAT yet",
    )


class DashboardDailyPoint(BaseModel):
    """Distinct shipments that moved into each state on that (UTC) day."""

    date: date
    in_transit: int
    delivered: int
    returned: int


class DashboardAppointments(BaseModel):
    """B2B appointment management counters (null sub-metric = not derivable)."""

    needed: Optional[int] = Field(
        default=None,
        description="EXCEPTION/APPOINTMENT_NEEDED, or appointment ID present without a booked slot",
    )
    at_risk: Optional[int] = Field(
        default=None, description="Booked slot starting within the next 24h and not delivered"
    )
    booked: Optional[int] = Field(
        default=None, description="Upcoming booked slot on an active shipment"
    )


class DashboardSummaryResponse(BaseModel):
    service_flow: ServiceFlow
    days: int
    generated_at: datetime
    stages: Union[B2CStageSummary, B2BStageSummary]
    performance: DashboardPerformance
    daily_series: List[DashboardDailyPoint]
    appointments: Optional[DashboardAppointments] = None
