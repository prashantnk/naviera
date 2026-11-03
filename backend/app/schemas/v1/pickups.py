import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    computed_field,
    conlist,
    constr,
    field_validator,
    model_validator,
)
from pydantic import (
    Field as PydanticField,
)
from sqlmodel import Field, SQLModel  # Using SQLModel for consistency

from app.core.money import money_to_float, to_money
from app.models.manifests import ServiceFlow

# Import Enums
from app.models.pickups import (
    ActivityType,
    AddressCategory,
    AddressScope,
    CodRemittanceStatus,
    DimensionUnit,
    DocumentType,
    FreightPaymentMode,
    NdrExceptionReason,
    PickupStatus,
    PickupStrategy,
    PickupTimeSlot,
    ProductCategory,
    ServiceOption,
    ServiceType,
    ShipmentType,
    WeightUnit,
)
from app.services.cod_payout import door_collectible as _door_collectible
from app.services.shipment_lifecycle import ShipmentLifecycleMachine

EWAY_BILL_MANDATORY_THRESHOLD = 50000
MAX_EXCEPTION_CHARGE_AMOUNT = 10_000_000.0
MAX_MEASURED_WEIGHT_KG = 100_000.0

PINCODE_PATTERN = r"^[1-9][0-9]{5}$"
"""H-06: an Indian PIN code is 6 digits and never starts with 0."""
PINCODE_ERROR = "Enter a valid 6-digit PIN code (it cannot start with 0)."
PHONE_SEPARATORS_RE = re.compile(r"[\s\-().]")
PHONE_COUNTRY_PREFIX_RE = re.compile(r"^(?:\+?91|0)(?=\d{10}$)")
PHONE_DIGITS_RE = re.compile(r"^[1-9]\d{9}$")
"""H-06: 10 digits after dropping spaces/dashes and a +91 / 91 / 0 prefix (mobile or STD landline)."""
PHONE_ERROR = "Enter a valid 10-digit phone number (optionally with +91)."
DIMENSIONS_REQUIRED_ERROR = "Every box needs a length, breadth and height greater than 0."


def validate_phone(value: Optional[str]) -> Optional[str]:
    """
    H-06 phone check. The number is stored as typed; only its digits are validated.

    Args:
        value: The phone as typed (None / blank allowed for optional fields).

    Returns:
        The value stripped of surrounding whitespace (None stays None).

    Raises:
        ValueError: not a 10-digit Indian number.
    """
    if value is None or not value.strip():
        return value
    digits = PHONE_COUNTRY_PREFIX_RE.sub("", PHONE_SEPARATORS_RE.sub("", value.strip()))
    if not PHONE_DIGITS_RE.match(digits):
        raise ValueError(PHONE_ERROR)
    return value.strip()


def validate_pincode(value: Optional[str]) -> Optional[str]:
    """H-06 pincode check (`^[1-9][0-9]{5}$`) after trimming; None stays None."""
    if value is None:
        return value
    trimmed = value.strip()
    if not re.match(PINCODE_PATTERN, trimmed):
        raise ValueError(PINCODE_ERROR)
    return trimmed


DELHIVERY_CARRIER_NAME = "Delhivery"
PRIME_CARRIER_NAME = "Logismart Prime"
CARRIER_NAMES = {
    ServiceOption.DELHIVERY_SURFACE: DELHIVERY_CARRIER_NAME,
    ServiceOption.DELHIVERY_EXPRESS: DELHIVERY_CARRIER_NAME,
    ServiceOption.PRIME_SURFACE: PRIME_CARRIER_NAME,
    ServiceOption.DELHIVERY_B2B_SURFACE: DELHIVERY_CARRIER_NAME,
}
"""Customer-facing carrier name per service option (transporter names stay internal, Q3)."""


def carrier_display_name(option: ServiceOption) -> str:
    """The carrier name shown on detail and public tracking pages."""
    return CARRIER_NAMES.get(option, DELHIVERY_CARRIER_NAME)


def declared_total_value(shipment_value: float, shipment_tax_value: float) -> float:
    """
    D-06: the declared goods total (value + tax), exact to the paisa.

    Args:
        shipment_value: Goods value before tax.
        shipment_tax_value: Tax on the goods.

    Returns:
        The total as a float (DOUBLE PRECISION column), computed in Decimal.
    """
    return money_to_float(to_money(shipment_value) + to_money(shipment_tax_value))


def assert_packages_have_dimensions(packages: Optional[List["PackageBase"]]) -> None:
    """
    A-26: declared boxes must have real sizes (0×0×0 guarantees a weight dispute later).

    Raises:
        ValueError: a box has a side ≤ 0.
    """
    for package in packages or []:
        if package.length <= 0 or package.breadth <= 0 or package.height <= 0:
            raise ValueError(DIMENSIONS_REQUIRED_ERROR)

# --- 1. Base Building Blocks ---


class AddressBase(SQLModel):
    name: str = Field(max_length=100)
    phone: str = Field(max_length=20)
    alternate_phone: Optional[str] = Field(default=None, max_length=20)
    email: Optional[EmailStr] = Field(default=None, max_length=100)
    company_name: Optional[str] = Field(default=None, max_length=100)
    gstin: Optional[str] = Field(default=None, max_length=15)
    address_line1: str = Field(max_length=255)
    address_line2: Optional[str] = Field(default=None, max_length=255)
    landmark: Optional[str] = Field(default=None, max_length=255)
    city: str = Field(max_length=50)
    state: str = Field(max_length=50)
    pincode: str = Field(min_length=6, max_length=10)
    country: str = Field(default="IN", max_length=2)
    category: AddressCategory = AddressCategory.HOME
    scope: AddressScope = AddressScope.PRIVATE
    is_saved: bool = (
        False  # default to transient addresses (Not treated as saved to DB)
    )


class PackageBase(SQLModel):
    length: float = Field(default=0.0, ge=0, description="Length")
    breadth: float = Field(default=0.0, ge=0, description="Breadth")
    height: float = Field(default=0.0, ge=0, description="Height")
    dimension_unit: DimensionUnit = DimensionUnit.CM
    weight: float = Field(gt=0, description="Weight")
    weight_unit: WeightUnit = WeightUnit.KG
    box_count: int = Field(default=1, gt=0)
    description: Optional[str] = Field(default=None, max_length=255)
    is_fragile: bool = False


class PaymentDetailsBase(SQLModel):
    currency: str = Field(default="INR", max_length=3)

    freight_payment_mode: FreightPaymentMode = FreightPaymentMode.PREPAID
    is_cod: bool = False
    cod_amount: float = Field(default=0.0, ge=0)
    add_shipping_to_cod: bool = False

    # Pricing Ledger & Tax
    base_freight: float = 0.0
    tax_amount: float = 0.0
    total_logistics_cost: float = 0.0
    chargeable_weight: float = 0.0
    pricing_breakdown: dict = {}

    # Compliance
    shipment_value: float = Field(default=0.0, ge=0)
    shipment_tax_value: float = Field(default=0.0, ge=0)
    shipment_total_value: float = Field(default=0.0, ge=0)
    hsn_code: Optional[str] = Field(default=None, max_length=255)
    invoice_numbers: Optional[conlist(constr(max_length=255))] = None
    invoice_date: Optional[date] = None
    eway_bill_numbers: Optional[conlist(constr(max_length=255))] = None

    @model_validator(mode="before")
    @classmethod
    def transform_legacy_fields(cls, data: dict) -> dict:
        if isinstance(data, dict):
            if "invoice_number" in data:
                val = data.pop("invoice_number")
                if val:
                    if data.get("invoice_numbers") is None:
                        data["invoice_numbers"] = []
                    data["invoice_numbers"].append(val)
            if "eway_bill_number" in data:
                val = data.pop("eway_bill_number")
                if val:
                    if data.get("eway_bill_numbers") is None:
                        data["eway_bill_numbers"] = []
                    data["eway_bill_numbers"].append(val)

            if "eway_bill_numbers" in data and isinstance(
                data["eway_bill_numbers"], list
            ):
                data["eway_bill_numbers"] = [
                    v for v in data["eway_bill_numbers"] if v and str(v).strip()
                ]

            val_base = float(data.get("shipment_value") or 0.0)
            val_tax = float(data.get("shipment_tax_value") or 0.0)
            if val_base > 0.0 or val_tax > 0.0:
                # D-06: the declared total is server-computed from the typed split, so it
                # can't be typed low to dodge the ₹50k e-way bill rule. A legacy body with
                # only `shipment_total_value` (no split) keeps its total.
                data["shipment_total_value"] = declared_total_value(val_base, val_tax)
        return data


# --- NEW: Document Schema ---
class PickupDocumentBase(SQLModel):
    document_type: DocumentType
    file_url: str = Field(max_length=255)
    file_name: str = Field(max_length=255)


# --- 2. Create Schemas (Inputs) ---


class AddressCreate(AddressBase):
    """Address input (booking snapshot or address book): H-06 pincode + phone checks."""

    @field_validator("pincode")
    @classmethod
    def _check_pincode(cls, value: str) -> str:
        return validate_pincode(value)  # type: ignore[return-value]

    @field_validator("phone", "alternate_phone")
    @classmethod
    def _check_phone(cls, value: Optional[str]) -> Optional[str]:
        return validate_phone(value)


class AddressUpdate(SQLModel):
    name: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    alternate_phone: Optional[str] = Field(default=None, max_length=20)
    gstin: Optional[str] = Field(default=None, max_length=15)
    email: Optional[EmailStr] = Field(default=None, max_length=100)
    company_name: Optional[str] = Field(default=None, max_length=100)
    address_line1: Optional[str] = Field(default=None, max_length=255)
    address_line2: Optional[str] = Field(default=None, max_length=255)
    landmark: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=50)
    state: Optional[str] = Field(default=None, max_length=50)
    pincode: Optional[str] = Field(default=None, min_length=6, max_length=10)
    country: Optional[str] = Field(default=None, max_length=2)
    category: Optional[AddressCategory] = None
    scope: Optional[AddressScope] = None

    @field_validator("pincode")
    @classmethod
    def _check_pincode(cls, value: Optional[str]) -> Optional[str]:
        return validate_pincode(value)

    @field_validator("phone", "alternate_phone")
    @classmethod
    def _check_phone(cls, value: Optional[str]) -> Optional[str]:
        return validate_phone(value)


class PackageCreate(PackageBase):
    pass


class PaymentDetailsCreate(PaymentDetailsBase):
    pass


class PickupDocumentCreate(PickupDocumentBase):
    pass


class PickupCreate(SQLModel):
    """
    The Master Input for Creating a Shipment.
    """

    order_reference_id: Optional[str] = Field(default=None, max_length=100)
    shipment_type: ShipmentType = ShipmentType.FORWARD
    service_type: ServiceType = ServiceType.SURFACE_ROAD
    requested_pickup_date: date
    pickup_time_slot: Optional[PickupTimeSlot] = None
    po_number: Optional[str] = Field(default=None, max_length=255)
    po_date: Optional[date] = None
    po_expiry_date: Optional[date] = None
    appointment_id: Optional[str] = Field(default=None, max_length=100)
    @field_validator("po_number")
    @classmethod
    def _validate_po_number(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        pos = [p.strip() for p in v.split(",") if p.strip()]
        if len(pos) > 5:
            raise ValueError("Maximum 5 comma-separated PO numbers are allowed.")
        return ",".join(pos)
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    pickup_strategy: Optional[PickupStrategy] = None

    product_category: ProductCategory
    other_category_description: Optional[str] = Field(default=None, max_length=255)

    reason_for_return: Optional[str] = Field(default=None, max_length=255)
    qc_required: bool = False
    qc_notes: Optional[str] = None
    pickup_qc_params: Optional[dict | list | str] = None
    ndr_reason: Optional[NdrExceptionReason] = None

    # Logic: ID vs Object
    pickup_address_id: Optional[UUID] = None
    new_pickup_address: Optional[AddressCreate] = None

    delivery_address_id: Optional[UUID] = None
    new_delivery_address: Optional[AddressCreate] = None

    packages: List[PackageCreate] = []
    payment_details: PaymentDetailsCreate

    # B2B Operational Flags
    is_blind_pickup: bool = False
    estimated_box_count: Optional[int] = None
    is_carriers_risk: bool = False

    # NEW: Documents List (Optional)
    documents: List[PickupDocumentCreate] = []

    # --- Pricing redesign (DESIGN.md v4 D3) ---
    service_flow: Optional[ServiceFlow] = Field(
        default=None,
        description="B2C or B2B, taken from the booking route (A-02). Legacy clients without it are inferred from B2B fields.",
    )
    service_option: Optional[ServiceOption] = Field(
        default=None,
        description="The option card the seller picked; defaults from the flow and service_type.",
    )
    expected_total: Optional[float] = Field(
        default=None,
        ge=0,
        description="The option's total_amount the seller saw; a different fresh price → 409 PRICE_CHANGED.",
    )
    door_delivery: bool = Field(
        default=False, description="Logismart Prime add-on: deliver to the consignee's door."
    )

    @field_validator("packages")
    @classmethod
    def _dims_required(cls, value: List[PackageCreate]) -> List[PackageCreate]:
        """A-26: every declared box needs length, breadth and height > 0."""
        assert_packages_have_dimensions(value)
        return value
    @model_validator(mode="after")
    def validate_business_logic(self) -> "PickupCreate":
        """
        Enforces critical business rules:
        1. Addresses must be provided (either ID or Object).
        2. Reverse shipments MUST have a reason.
        3. SECURITY: Cannot create 'WAREHOUSE' addresses on the fly.
        """
        if self.pickup_qc_params is not None:
            self.qc_required = True
            if not self.qc_notes:
                if isinstance(self.pickup_qc_params, dict):
                    notes = (
                        self.pickup_qc_params.get("qc_notes")
                        or self.pickup_qc_params.get("notes")
                        or ", ".join(
                            f"{k}: {v}" for k, v in self.pickup_qc_params.items()
                        )
                    )
                    self.qc_notes = str(notes)[:255]
                elif isinstance(self.pickup_qc_params, list):
                    self.qc_notes = ", ".join(str(x) for x in self.pickup_qc_params)[
                        :255
                    ]
                else:
                    self.qc_notes = str(self.pickup_qc_params)[:255]

        # --- Rule 1: Address Presence ---
        if not self.pickup_address_id and not self.new_pickup_address:
            raise ValueError(
                "Either pickup_address_id OR new_pickup_address is required"
            )
        if not self.delivery_address_id and not self.new_delivery_address:
            raise ValueError(
                "Either delivery_address_id OR new_delivery_address is required"
            )

        # --- Rule 2: Reverse Logic ---
        if self.shipment_type == ShipmentType.REVERSE and not self.reason_for_return:
            raise ValueError(
                "reason_for_return is mandatory when shipment_type is REVERSE"
            )

        # --- Rule 4: ProductCategory OTHER requires description ---
        if (
            self.product_category == ProductCategory.OTHER
            and not self.other_category_description
        ):
            raise ValueError(
                "other_category_description is required when product_category is OTHER"
            )

        if self.payment_details is not None:
            # --- Rule A: E-Way Bill Limit ---
            if (
                self.payment_details.shipment_total_value
                >= EWAY_BILL_MANDATORY_THRESHOLD
            ):
                has_eway_bill_number = any(
                    bool(eb.strip())
                    for eb in (self.payment_details.eway_bill_numbers or [])
                )
                has_eway_bill_doc = any(
                    doc.document_type == DocumentType.EWAY_BILL
                    for doc in self.documents
                )
                if not (has_eway_bill_number or has_eway_bill_doc):
                    raise ValueError(
                        f"E-Way Bill is mandatory for shipment value >= {EWAY_BILL_MANDATORY_THRESHOLD}"
                    )

            # --- Rule D: COD Limit ---
            # A-01: `cod_amount` is the goods COD the seller typed; shipping is added on top
            # (add_shipping_to_cod) by the backend, so the goods COD never exceeds the goods value.
            if self.payment_details.is_cod:
                if self.payment_details.cod_amount <= 0:
                    raise ValueError("COD amount must be greater than 0")
                if (
                    self.payment_details.cod_amount
                    > self.payment_details.shipment_total_value
                ):
                    raise ValueError("COD amount cannot exceed shipment total value")

        return self

    @model_validator(mode="after")
    def validate_b2b_rules(self) -> "PickupCreate":
        # --- B2B Validation: Blind Pickups ---
        if self.is_blind_pickup:
            if not self.estimated_box_count or self.estimated_box_count <= 0:
                raise ValueError(
                    "estimated_box_count must be greater than 0 when is_blind_pickup is True"
                )
            if self.packages:
                raise ValueError("packages list must be empty for blind pickups")

        # --- B2B Validation: Carrier's Risk ---
        if self.is_carriers_risk:
            if (
                not self.payment_details
                or self.payment_details.shipment_total_value <= 0
            ):
                raise ValueError(
                    "shipment_total_value must be greater than 0 when is_carriers_risk is True"
                )

        return self


# --- 3. Read Schemas (Outputs) ---


class AddressRead(AddressBase):
    id: UUID
    user_id: UUID


class PackageRead(PackageBase):
    id: UUID


class PaymentDetailsRead(PaymentDetailsBase):
    id: UUID
    cod_remittance_status: CodRemittanceStatus
    pricing_breakdown: dict = {}
    freight_collectible: float = Field(
        default=0.0,
        description="TO_PAY freight the rider still collects at the door (server-computed, read-only)",
    )

    @computed_field
    def invoice_number(self) -> Optional[str]:
        return self.invoice_numbers[0] if self.invoice_numbers else None

    @computed_field
    def eway_bill_number(self) -> Optional[str]:
        return self.eway_bill_numbers[0] if self.eway_bill_numbers else None


class PickupDocumentRead(PickupDocumentBase):
    id: UUID
    uploaded_at: datetime


class PickupRead(SQLModel):
    """
    Output schema.
    """

    id: UUID
    tracking_id: Optional[str]
    status: PickupStatus
    latest_status_comment: Optional[str] = None
    order_reference_id: Optional[str] = None
    shipment_type: ShipmentType
    service_type: ServiceType
    requested_pickup_date: date
    pickup_time_slot: Optional[PickupTimeSlot] = None
    po_number: Optional[str] = None
    po_date: Optional[date] = None
    po_expiry_date: Optional[date] = None
    appointment_id: Optional[str] = None
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    pickup_strategy: Optional[PickupStrategy] = None

    # B2B Operational Flags
    is_blind_pickup: bool
    estimated_box_count: Optional[int] = None
    is_carriers_risk: bool
    delivered_box_count: Optional[int] = None

    product_category: ProductCategory
    other_category_description: Optional[str] = None

    reason_for_return: Optional[str] = None
    qc_required: bool
    qc_notes: Optional[str] = None
    ndr_reason: Optional[NdrExceptionReason] = None
    ndr_attempt_count: int = 0
    ndr_remark: Optional[str] = None
    exception_raised_at: Optional[datetime] = None
    charge_amount: Optional[float] = None
    delivery_otp: Optional[str] = Field(default=None, max_length=6)
    pod_received_by: Optional[str] = Field(default=None, max_length=100)
    created_by_user_id: UUID
    creator_email: Optional[str] = None
    manifest_id: Optional[UUID] = None
    # Pricing redesign (M-P1): the booked service option and the carrier's own AWB.
    service_option: ServiceOption = ServiceOption.DELHIVERY_SURFACE
    carrier_awb: Optional[str] = None
    transporter_name: Optional[str] = None
    """Prime transporter name from the lane snapshot, populated for tenant staff only."""


    # Nested Objects
    pickup_address: AddressRead
    delivery_address: AddressRead
    packages: List[PackageRead]
    payment_details: Optional[PaymentDetailsRead] = None
    documents: List[PickupDocumentRead] = []

    created_at: datetime

    @computed_field
    def carrier_name(self) -> str:
        """Who moves the parcel, for the detail page ("Delhivery" / "Logismart Prime")."""
        return carrier_display_name(self.service_option)

    @computed_field
    def door_collectible(self) -> float:
        """
        Cash the rider collects at the door (COD + any freight still due), read-only.

        Computed only by `services.cod_payout.door_collectible` (frozen once Delivered), so the
        ops card, the label and the detail pages never recompute it (WP2 / E-06). 0 = prepaid.
        """
        return money_to_float(_door_collectible(self.payment_details))

    @computed_field
    def allowed_next_statuses(self) -> List[PickupStatus]:
        """
        Statuses the server accepts next from the current one (E-11), straight from
        `ShipmentLifecycleMachine`, so the status dialog never offers a move that 400s.
        """
        return ShipmentLifecycleMachine.allowed_next_statuses(self.status)

    @computed_field
    def total_box_count(self) -> int:
        if self.is_blind_pickup:
            return self.estimated_box_count or 0
        return sum(pkg.box_count for pkg in self.packages or [])


# --- 4. Update Schemas (The Edit Flow) ---


class PackageUpdate(PackageBase):
    """
    Used for rditing packages inside a shipment.
    - id: If present, we update the existing row. If None, we create a new row.
    """

    id: Optional[UUID] = None


class PickupDocumentUpdate(PickupDocumentBase):
    """
    Used for syncing documents.
    - id: If present, we keep/update it. If None, we create a new record.
    """

    id: Optional[UUID] = None


class PickupUpdate(SQLModel):
    """
    The Master Payload for Editing a Shipment.
    Supports both User corrections and Admin operations.
    All fields are Optional -> "Patch" semantics.
    """

    # --- 1. Lifecycle & Audit ---
    status: Optional[PickupStatus] = None
    comment: Optional[str] = Field(
        default=None, max_length=255
    )  # Reason for change (Required for Status changes)
    is_public: bool = False  # Should this update be visible on the Tracking Page?

    # --- 2. Scheduling & Reference ---
    requested_pickup_date: Optional[date] = None
    order_reference_id: Optional[str] = Field(default=None, max_length=100)
    pickup_time_slot: Optional[PickupTimeSlot] = None
    # Service speed: editable only before pickup (hard block H-8, enforced by the service layer).
    service_type: Optional[ServiceType] = None
    service_option: Optional[ServiceOption] = None
    po_number: Optional[str] = Field(default=None, max_length=255)
    po_date: Optional[date] = None
    po_expiry_date: Optional[date] = None
    appointment_id: Optional[str] = Field(default=None, max_length=100)
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    pickup_strategy: Optional[PickupStrategy] = None

    # --- B2B Flags ---
    is_blind_pickup: Optional[bool] = None
    estimated_box_count: Optional[int] = None
    is_carriers_risk: Optional[bool] = None

    @field_validator("po_number")
    @classmethod
    def _validate_po_number(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        pos = [p.strip() for p in v.split(",") if p.strip()]
        if len(pos) > 5:
            raise ValueError("Maximum 5 comma-separated PO numbers are allowed.")
        return ",".join(pos)

    # --- 3. Cargo Details ---
    product_category: Optional[ProductCategory] = None
    other_category_description: Optional[str] = Field(default=None, max_length=255)

    reason_for_return: Optional[str] = Field(default=None, max_length=255)
    qc_required: Optional[bool] = None
    qc_notes: Optional[str] = None
    ndr_reason: Optional[NdrExceptionReason] = None
    # Raising an exception (status=EXCEPTION, Admin/Ops only):
    ndr_remark: Optional[str] = Field(
        default=None, max_length=255, description="Field-agent remark shown to the merchant"
    )
    charge_amount: Optional[float] = Field(
        default=None,
        ge=0,
        le=MAX_EXCEPTION_CHARGE_AMOUNT,
        description="INR charge to acknowledge (FREIGHT_COLLECTION / ADDITIONAL_CHARGES / WEIGHT_DISCREPANCY)",
    )
    measured_weight_kg: Optional[float] = Field(
        default=None,
        gt=0,
        le=MAX_MEASURED_WEIGHT_KG,
        description="Hub-measured weight for WEIGHT_DISCREPANCY (re-billed if the merchant accepts)",
    )
    delivery_otp: Optional[str] = Field(default=None, max_length=6)
    pod_received_by: Optional[str] = Field(default=None, max_length=100)
    expected_cod_amount: Optional[float] = Field(
        default=None,
        ge=0,
        description="COD collectible shown on the rider's screen when marking Delivered (A-10)",
    )

    # --- 4. Address Corrections (The Snapshot Strategy) ---
    # Scenario A: User picks a different existing address
    pickup_address_id: Optional[UUID] = None
    delivery_address_id: Optional[UUID] = None

    # Scenario B: User manually edits the text (Creates a new snapshot)
    new_pickup_address: Optional[AddressCreate] = None
    new_delivery_address: Optional[AddressCreate] = None

    # --- 5. Package Adjustments ---
    # The Frontend sends the *complete* list of desired packages.
    packages: Optional[List[PackageUpdate]] = None

    # --- 6. Document Adjustments ---
    documents: Optional[List[PickupDocumentUpdate]] = None

    # --- 7. Financials ---
    # We reuse PaymentDetailsCreate because usually, you update the whole block (Amount + Mode)
    payment_details: Optional[PaymentDetailsCreate] = None

    @field_validator("packages")
    @classmethod
    def _dims_required(cls, value: Optional[List[PackageUpdate]]) -> Optional[List[PackageUpdate]]:
        """A-26: every declared box needs length, breadth and height > 0."""
        assert_packages_have_dimensions(value)
        return value


# --- 5. Timeline & Tracking Schemas (Read Only) ---


class ShipmentActivityRead(SQLModel):
    """
    For Admins: The complete history of a shipment.
    """

    id: UUID
    timestamp: datetime
    user_id: UUID
    activity_type: ActivityType
    summary: Optional[str] = None
    comment: Optional[str] = None
    is_public: bool
    diff: dict = {}  # Admins need to see the technical changes


class PublicActivityRead(SQLModel):
    """
    For Customers: A sanitized timeline event.
    No 'diff', no 'user_id', no internal 'comment'.
    """

    timestamp: datetime
    status_title: str  # Derived from summary/status
    message: Optional[str] = None  # Derived from public comment


class PublicTrackingRead(SQLModel):
    """
    The Public Tracking Page Data.
    Minimal info to prove shipment exists and show status.
    """

    model_config = ConfigDict(populate_by_name=True)

    tracking_id: str
    status: PickupStatus
    current_location: str = "Processing"  # Placeholder for now
    estimated_delivery: Optional[date] = None
    carrier_name: Optional[str] = None
    """Who moves the parcel ("Delhivery" / "Logismart Prime"); never transporter names."""
    carrier_awb: Optional[str] = None
    """The carrier's own AWB (Delhivery waybill) once ops entered it."""
    delivery_otp: Optional[str] = Field(default=None, max_length=6)
    pod_received_by: Optional[str] = Field(default=None, max_length=100)
    timeline: List[PublicActivityRead] = PydanticField(
        default=[], validation_alias="tracking_events"
    )
    package_details: List[PackageRead] = []


IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


class AppointmentUpdate(BaseModel):
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    po_number: Optional[str] = PydanticField(default=None, max_length=255)
    po_expiry_date: Optional[date] = None

    @field_validator("appointment_start", "appointment_end")
    @classmethod
    def _require_timezone_aware_datetime(
        cls, value: Optional[datetime]
    ) -> Optional[datetime]:
        """Reject naive appointment timestamps so IST/UTC offsets are explicit (D-09/D-17)."""
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "Appointment timestamps must include an explicit timezone offset (e.g. +05:30 or Z)."
            )
        return value

    @field_validator("po_number")
    @classmethod
    def _validate_po_number(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        pos = [p.strip() for p in v.split(",") if p.strip()]
        if len(pos) > 5:
            raise ValueError("Maximum 5 comma-separated PO numbers are allowed.")
        return ",".join(pos)

    @model_validator(mode="after")
    def _validate_appointment_window(self) -> "AppointmentUpdate":
        """Enforce start < end, non-past appointment date, and PO expiry >= appointment date (D-17)."""
        if (self.appointment_start is None) != (self.appointment_end is None):
            raise ValueError(
                "Both appointment_start and appointment_end must be provided together."
            )
        if self.appointment_start is not None and self.appointment_end is not None:
            if self.appointment_start >= self.appointment_end:
                raise ValueError("appointment_end must be after appointment_start.")
            appointment_ist_date = self.appointment_start.astimezone(IST_TIMEZONE).date()
            today_ist_date = datetime.now(IST_TIMEZONE).date()
            if appointment_ist_date < today_ist_date:
                raise ValueError("Appointment date cannot be in the past.")
            if (
                self.po_expiry_date is not None
                and self.po_expiry_date < appointment_ist_date
            ):
                raise ValueError(
                    "po_expiry_date cannot be earlier than the appointment date."
                )
        return self


class NdrExceptionResolveRequest(SQLModel):
    action: str = Field(max_length=100)
    is_cod: Optional[bool] = None
    eway_bill_number: Optional[str] = Field(default=None, max_length=50)
    consignee_phone: Optional[str] = Field(default=None, max_length=30)
    consignee_address_line1: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None

