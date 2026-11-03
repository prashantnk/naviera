"""
DTOs for the Delivery Exceptions / NDR API (`/api/v1/exceptions`).
Spring Boot Equivalent: request/response DTO classes with Bean Validation.
"""

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, model_validator
from pydantic import Field as PydanticField
from sqlmodel import Field, SQLModel

from app.models.exceptions import ExceptionCategory
from app.models.manifests import ServiceFlow
from app.models.pickups import (
    DocumentType,
    FreightPaymentMode,
    NdrAction,
    NdrExceptionReason,
    PickupStatus,
    ShipmentType,
)
from app.services.ndr_rules import MAX_BULK_ACTION_SHIPMENTS

EXCEPTIONS_DEFAULT_PAGE_SIZE = 20
EXCEPTIONS_MAX_PAGE_SIZE = 100
MAX_NOTES_LENGTH = 500
MAX_URL_LENGTH = 1000


class ExceptionPaymentMode(str, Enum):
    """What the consignee pays at the door (Delhivery "Payment" column)."""

    COD = "COD"
    PREPAID = "PREPAID"


class ExceptionCategoryCount(SQLModel):
    """Live count for one category / group tab."""

    category: ExceptionCategory
    label: str
    total: int
    actionable: int


class ExceptionSummaryResponse(SQLModel):
    """Counts powering the category menu, tabs and dashboard / sidebar badges."""

    service_flow: ServiceFlow
    total: int
    actionable: int
    non_actionable: int
    categories: List[ExceptionCategoryCount]


class ExceptionConsignee(SQLModel):
    """The customer-side party: consignee for forward, pickup customer for reverse."""

    name: str
    phone: str
    address_line1: str
    address_line2: Optional[str] = None
    landmark: Optional[str] = None
    city: str
    state: str
    pincode: str


class ExceptionRow(SQLModel):
    """One on-hold shipment with everything the exceptions grid needs (server-computed)."""

    shipment_id: UUID
    tracking_id: Optional[str] = None
    order_reference_id: Optional[str] = None
    service_flow: ServiceFlow
    shipment_type: ShipmentType
    status: PickupStatus
    ndr_reason: Optional[NdrExceptionReason] = None
    category: Optional[ExceptionCategory] = None
    is_actionable: bool
    awaiting_ops: bool = Field(
        default=False, description="Merchant already responded (HOLD / DISPUTE_WEIGHT)"
    )
    allowed_actions: List[NdrAction] = []
    attempts: int
    max_attempts: int
    last_remark: Optional[str] = None
    exception_raised_at: Optional[datetime] = None
    aging_days: int
    consignee: ExceptionConsignee
    origin_city: str
    destination_city: str
    payment_mode: ExceptionPaymentMode
    freight_payment_mode: Optional[FreightPaymentMode] = None
    cod_amount: float = 0.0
    charge_amount: Optional[float] = None
    charge_amount_payable: Optional[float] = Field(
        default=None,
        description=(
            "What the shipper's wallet is actually debited if they accept the charge, GST "
            "included (A-20). `charge_amount` is the ops-entered figure (GST-exclusive for "
            "additional / weight charges, GST-inclusive for freight collection)."
        ),
    )
    logismart_liable_allowed: bool = Field(
        default=False,
        description="True when staff may waive the RTO charge as 'Logismart liable' (DAMAGED / SHORT_SHIPMENT).",
    )
    box_count: int
    pdd: Optional[date] = Field(
        default=None, description="Promised delivery date (booked appointment date)"
    )
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    created_at: datetime


class ExceptionListResponse(SQLModel):
    """Paginated exception rows."""

    items: List[ExceptionRow]
    total: int
    page: int
    size: int
    pages: int


class NdrActionRequest(BaseModel):
    """
    Merchant action on one on-hold shipment. Only the fields relevant to the
    chosen action are read; the action itself is validated against the
    server-side allowed-actions matrix.
    """

    action: NdrAction
    consignee_name: Optional[str] = PydanticField(
        default=None,
        min_length=2,
        max_length=100,
        description="New consignee name (same address and pincode)",
    )
    consignee_phone: Optional[str] = PydanticField(
        default=None, max_length=20, pattern=r"^\+?[0-9 ]{10,20}$"
    )
    consignee_address_line1: Optional[str] = PydanticField(
        default=None, min_length=3, max_length=255
    )
    consignee_address_line2: Optional[str] = PydanticField(default=None, max_length=255)
    landmark: Optional[str] = PydanticField(default=None, max_length=255)
    consignee_pincode: Optional[str] = PydanticField(
        default=None,
        min_length=6,
        max_length=10,
        description="Optional guard: address edits must stay within the same pincode",
    )
    is_cod: Optional[bool] = None
    eway_bill_number: Optional[str] = PydanticField(default=None, max_length=20)
    invoice_number: Optional[str] = PydanticField(default=None, max_length=50)
    document_type: Optional[DocumentType] = None
    document_url: Optional[str] = PydanticField(default=None, max_length=MAX_URL_LENGTH)
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    preferred_date: Optional[date] = None
    notes: Optional[str] = PydanticField(default=None, max_length=MAX_NOTES_LENGTH)
    delivered_box_count: Optional[int] = PydanticField(
        default=None,
        gt=0,
        description="PARTIAL_DELIVERY: boxes actually handed over (short shipment)",
    )
    revised_cod_amount: Optional[float] = PydanticField(
        default=None,
        ge=0,
        description="PARTIAL_DELIVERY: revised goods COD for the boxes delivered (COD fee re-priced)",
    )
    logismart_liable: bool = PydanticField(
        default=False,
        description="RETURN_TO_ORIGIN on a DAMAGED / SHORT_SHIPMENT exception: Logismart is at fault, so the RTO charge is waived. Tenant staff only (A-09); a shipper sending it gets 403",
    )

    @model_validator(mode="after")
    def _validate_appointment_window(self) -> "NdrActionRequest":
        """An appointment slot must end after it starts."""
        if (
            self.appointment_start is not None
            and self.appointment_end is not None
            and self.appointment_end <= self.appointment_start
        ):
            raise ValueError("appointment_end must be after appointment_start")
        return self


class BulkNdrActionRequest(BaseModel):
    """Bulk action on up to 200 shipments (REATTEMPT / RETURN_TO_ORIGIN / RESCHEDULE_PICKUP / CANCEL_PICKUP)."""

    action: NdrAction
    shipment_ids: List[UUID] = PydanticField(
        min_length=1, max_length=MAX_BULK_ACTION_SHIPMENTS
    )


class BulkActionFailure(SQLModel):
    """Why one shipment in a bulk request was not processed."""

    shipment_id: UUID
    reason: str


class BulkNdrActionResponse(SQLModel):
    """Partial-success result of a bulk action."""

    succeeded: List[UUID]
    failed: List[BulkActionFailure]
