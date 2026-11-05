import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.manifests import ManifestStatus, ServiceFlow
from app.models.pickups import PickupStatus
from app.schemas.v1.pickups import PackageCreate
from app.schemas.v1.repricing import (
    MAX_EVIDENCE_URLS,
    MAX_REMARK_LENGTH,
    validate_evidence_urls,
)

FAILURE_REASON_MAX_LENGTH = 255


class ManifestShipmentItem(BaseModel):
    """Light shipment item attached to a Pickup Request response for the AWB handover checklist."""

    id: uuid.UUID
    tracking_id: Optional[str] = None
    order_reference_id: str
    package_count: int = 0
    status: PickupStatus


class ManifestCreate(BaseModel):
    """
    Create a Pickup Request (PUR).

    - B2B (default, backward compatible): blind pickups allowed, 'total_boxes' honoured for blind.
    - B2C: 'is_blind_pickup' must be False, at least one shipment is required and
      'total_boxes' is always computed on the server from the linked shipments.
    """

    pickup_address_id: uuid.UUID
    scheduled_date: date
    time_slot: str
    service_flow: ServiceFlow = ServiceFlow.B2B
    is_blind_pickup: bool = False
    total_boxes: int = Field(default=0, ge=0)
    shipment_ids: List[uuid.UUID] = Field(default_factory=list)


class ManifestResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    pickup_address_id: uuid.UUID
    scheduled_date: date
    time_slot: str
    is_blind_pickup: bool
    total_boxes: int
    status: ManifestStatus
    created_at: date
    service_flow: ServiceFlow = ServiceFlow.B2B
    pickup_request_number: Optional[str] = None
    failure_reason: Optional[str] = None
    pickup_otp: Optional[str] = None
    pickup_otp_verified_at: Optional[datetime] = None
    pickup_otp_verified_by: Optional[uuid.UUID] = None
    pickup_otp_override_reason: Optional[str] = None
    pickup_location_name: str = ""
    pickup_location_address: str = ""
    expected_awbs: int = 0
    picked_awbs: int = 0
    shipments: List[ManifestShipmentItem] = Field(default_factory=list)
    notice: Optional[str] = None
    """Set on create when the requested slot was moved to the next slot (plan D2)."""

    model_config = {"from_attributes": True}


class ManifestDispatchMeasurement(BaseModel):
    """
    "Actual pieces" recorded by the rider for one picked LR at the doorstep (plan B5 / A-11).
    Either explicit `packages` (from the full measurement dialog) or `actual_pieces` (one-tap
    count) is provided. When `actual_pieces` is sent, the backend scales the declared package
    lines (no re-bill when the count matches; blind LRs record the carton count and wait for
    hub measurement).
    """

    shipment_id: uuid.UUID
    packages: Optional[List[PackageCreate]] = Field(default=None)
    actual_pieces: Optional[int] = Field(default=None, ge=1, le=5000)
    evidence_urls: List[str] = Field(default_factory=list, max_length=MAX_EVIDENCE_URLS)
    remark: Optional[str] = Field(default=None, max_length=MAX_REMARK_LENGTH)

    @field_validator("evidence_urls")
    @classmethod
    def _clean_evidence_urls(cls, urls: List[str]) -> List[str]:
        """Only http(s) photo links are accepted."""
        return validate_evidence_urls(urls)

    @model_validator(mode="after")
    def _require_packages_or_pieces(self) -> "ManifestDispatchMeasurement":
        """Requires either explicit packages or actual_pieces >= 1."""
        has_packages = bool(self.packages)
        has_pieces = self.actual_pieces is not None and self.actual_pieces >= 1
        if not has_packages and not has_pieces:
            raise ValueError("Provide either 'packages' or 'actual_pieces' (>= 1).")
        return self


class ManifestDispatchRequest(BaseModel):
    """
    Optional body of 'POST /manifests/{id}/dispatch'.

    - `picked_shipment_ids`: partial pickup AWB checklist (omitted = every linked LR picked).
    - `measurements`: optional actual pieces per picked LR (also optional for blind LRs).
    - `pickup_otp`: 6-digit pickup handover OTP shared by the seller with the pickup executive.
    - `pickup_otp_override_reason`: mandatory audit reason when an Owner/Admin overrides OTP verification.
    """

    picked_shipment_ids: Optional[List[uuid.UUID]] = None
    measurements: Optional[List[ManifestDispatchMeasurement]] = None
    pickup_otp: Optional[str] = Field(default=None, max_length=32)
    pickup_otp_override_reason: Optional[str] = Field(
        default=None, max_length=FAILURE_REASON_MAX_LENGTH
    )

    @model_validator(mode="after")
    def _one_measurement_per_lr(self) -> "ManifestDispatchRequest":
        """Rejects two measurements for the same LR in one request."""
        ids = [m.shipment_id for m in self.measurements or []]
        if len(ids) != len(set(ids)):
            raise ValueError("Send at most one measurement per shipment.")
        return self


class ManifestShipmentsAdd(BaseModel):
    """Body of 'POST /manifests/{id}/shipments' (Delhivery 'add to today's pickup')."""

    shipment_ids: List[uuid.UUID] = Field(min_length=1)


class ManifestNotPickedRequest(BaseModel):
    """Body of the Admin-only 'POST /manifests/{id}/not-picked' outcome."""

    failure_reason: str = Field(min_length=1, max_length=FAILURE_REASON_MAX_LENGTH)


class EligibleShipmentRead(BaseModel):
    """Light row for the Create Pickup Request shipment picker (OPEN shipments of one location)."""

    id: uuid.UUID
    tracking_id: Optional[str] = None
    order_reference_id: Optional[str] = None
    delivery_city: str
    delivery_pincode: str
    package_count: int
    total_weight_kg: float
    created_at: datetime


class PickupCandidatesResponse(BaseModel):
    """
    Result of validating a multi-selection from the Shipments list ('Add to Pickup').
    'candidates' are SCHEDULED pickups (today or later) of the same flow and location.
    """

    service_flow: ServiceFlow
    pickup_address_id: uuid.UUID
    pickup_location_name: str
    candidates: List[ManifestResponse]
