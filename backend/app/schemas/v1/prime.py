"""
Staff-only API shapes for the Logismart Prime rate table (API_CONTRACT.md §7).

Money, kg, cm and percent travel as JSON numbers (rupees, 2 dp) computed by the backend.
`transporter_name` and `markup_percent` appear only here (staff endpoints); the response
audit forbids them in customer responses.

Spring analogy: request/response DTOs with Bean Validation (`@PositiveOrZero`, `@Positive`).
"""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from app.models.prime import PrimeDeliveryType, PrimeLaneMode

MAX_RATE_VALUE = 99_999_999.99
"""Largest value a NUMERIC(10,2) column holds."""

MAX_TAT_HOURS = 24 * 60
"""60 days: anything longer is a typo."""


class PrimeZoneRead(SQLModel):
    """One delivery zone with its pincode count."""

    id: uuid.UUID
    name: str
    pincode_count: int


class PrimeLaneRead(SQLModel):
    """One lane as shown in the staff lanes editor (zones by name)."""

    id: uuid.UUID
    origin_zone: str
    dest_zone: str
    mode: PrimeLaneMode
    transporter_name: str
    tat_hours: int
    rate_per_kg: float
    min_lr_charge: float
    docket_charge: float
    min_chargeable_kg: float
    volumetric_divisor: float
    max_dimension_cm: float
    delivery_type: PrimeDeliveryType
    oda_per_kg: float
    oda_min: float
    odd_weight_per_kg: float
    odd_weight_min: float
    pickup_per_kg: float
    pickup_min: float
    door_delivery_per_kg: float
    door_delivery_min: float
    markup_percent: float
    is_active: bool
    updated_at: datetime


class PrimeLanePatch(SQLModel):
    """
    Any subset of a lane's editable numbers plus `is_active`.
    Unknown fields are rejected (422) so a typo never silently does nothing.
    """

    model_config = ConfigDict(extra="forbid")

    tat_hours: Optional[int] = Field(default=None, gt=0, le=MAX_TAT_HOURS)
    rate_per_kg: Optional[float] = Field(default=None, gt=0, le=MAX_RATE_VALUE)
    min_lr_charge: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    docket_charge: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    min_chargeable_kg: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    volumetric_divisor: Optional[float] = Field(default=None, gt=0, le=MAX_RATE_VALUE)
    max_dimension_cm: Optional[float] = Field(default=None, gt=0, le=MAX_RATE_VALUE)
    oda_per_kg: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    oda_min: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    odd_weight_per_kg: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    odd_weight_min: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    pickup_per_kg: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    pickup_min: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    door_delivery_per_kg: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    door_delivery_min: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    markup_percent: Optional[float] = Field(default=None, ge=0, le=MAX_RATE_VALUE)
    is_active: Optional[bool] = None


class PrimeImportIssue(SQLModel):
    """One import problem; `row` is the 1-based CSV line (header = 1), None for file-level issues."""

    row: Optional[int] = None
    message: str


class PrimeImportReport(SQLModel):
    """What a lanes CSV import did (or would do, on a dry run)."""

    created: int = 0
    updated: int = 0
    deactivated: int = 0
    errors: List[PrimeImportIssue] = []
    warnings: List[PrimeImportIssue] = []
