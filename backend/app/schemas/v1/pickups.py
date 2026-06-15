from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import EmailStr, model_validator, constr, conlist, computed_field
from sqlmodel import Field, SQLModel  # Using SQLModel for consistency

# Import Enums
from app.models.pickups import (
    PickupStrategy,
    ActivityType,
    AddressCategory,
    AddressScope,
    DocumentType,
    FreightPaymentMode,
    CodRemittanceStatus,
    PickupStatus,
    PickupTimeSlot,
    ProductCategory,
    ServiceType,
    ShipmentType,
    DimensionUnit,
    WeightUnit,
    NdrExceptionReason,
)

# --- 1. Base Building Blocks ---


class AddressBase(SQLModel):
    name: str = Field(..., max_length=255)
    phone: str = Field(..., max_length=255)
    alternate_phone: Optional[str] = Field(default=None, max_length=255)
    email: Optional[EmailStr] = None
    company_name: Optional[str] = Field(default=None, max_length=255)
    gstin: Optional[str] = Field(default=None, max_length=255)
    address_line1: str = Field(..., max_length=255)
    address_line2: Optional[str] = Field(default=None, max_length=255)
    landmark: Optional[str] = Field(default=None, max_length=255)
    city: str = Field(..., max_length=255)
    state: str = Field(..., max_length=255)
    pincode: str = Field(..., max_length=255)
    country: str = Field(default="IN", max_length=255)
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
    currency: str = Field(default="INR", max_length=10)
    
    freight_payment_mode: FreightPaymentMode = FreightPaymentMode.PREPAID
    is_cod: bool = False
    cod_amount: float = Field(default=0.0, ge=0)
    add_shipping_to_cod: bool = False

    # Pricing Ledger & Tax
    base_freight: float = 0.0
    tax_amount: float = 0.0
    total_logistics_cost: float = 0.0
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
                    data.setdefault("invoice_numbers", []).append(val)
            if "eway_bill_number" in data:
                val = data.pop("eway_bill_number")
                if val:
                    data.setdefault("eway_bill_numbers", []).append(val)
            
            if "eway_bill_numbers" in data and isinstance(data["eway_bill_numbers"], list):
                data["eway_bill_numbers"] = [
                    v for v in data["eway_bill_numbers"] if v and str(v).strip()
                ]
        return data



# --- NEW: Document Schema ---
class PickupDocumentBase(SQLModel):
    document_type: DocumentType
    file_url: str = Field(..., max_length=255)
    file_name: str = Field(..., max_length=255)


# --- 2. Create Schemas (Inputs) ---


class AddressCreate(AddressBase):
    pass

class AddressUpdate(SQLModel):
    name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=255)
    alternate_phone: Optional[str] = Field(default=None, max_length=255)
    gstin: Optional[str] = Field(default=None, max_length=255)
    email: Optional[EmailStr] = None
    company_name: Optional[str] = Field(default=None, max_length=255)
    address_line1: Optional[str] = Field(default=None, max_length=255)
    address_line2: Optional[str] = Field(default=None, max_length=255)
    landmark: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=255)
    state: Optional[str] = Field(default=None, max_length=255)
    pincode: Optional[str] = Field(default=None, max_length=255)
    country: Optional[str] = Field(default=None, max_length=255)
    category: Optional[AddressCategory] = None
    scope: Optional[AddressScope] = None


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

    order_reference_id: Optional[str] = Field(default=None, max_length=255)
    shipment_type: ShipmentType = ShipmentType.FORWARD
    service_type: ServiceType = ServiceType.SURFACE_ROAD
    requested_pickup_date: date
    pickup_time_slot: Optional[PickupTimeSlot] = None
    po_number: Optional[str] = Field(default=None, max_length=255)
    po_date: Optional[date] = None
    appointment_id: Optional[str] = Field(default=None, max_length=100)
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    pickup_strategy: Optional[PickupStrategy] = None

    product_category: ProductCategory
    other_category_description: Optional[str] = Field(default=None, max_length=255)

    reason_for_return: Optional[str] = Field(default=None, max_length=255)
    ndr_reason: Optional[NdrExceptionReason] = None

    # Logic: ID vs Object
    pickup_address_id: Optional[UUID] = None
    new_pickup_address: Optional[AddressCreate] = None

    delivery_address_id: Optional[UUID] = None
    new_delivery_address: Optional[AddressCreate] = None

    packages: List[PackageCreate]
    payment_details: Optional[PaymentDetailsCreate] = None

    # NEW: Documents List (Optional)
    documents: List[PickupDocumentCreate] = []

    @model_validator(mode="after")
    def validate_business_logic(self) -> "PickupCreate":
        """
        Enforces critical business rules:
        1. Addresses must be provided (either ID or Object).
        2. Reverse shipments MUST have a reason.
        3. SECURITY: Cannot create 'WAREHOUSE' addresses on the fly.
        """
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
        if self.product_category == ProductCategory.OTHER and not self.other_category_description:
            raise ValueError(
                "other_category_description is required when product_category is OTHER"
            )

        if self.payment_details is not None:
            # --- Rule A: E-Way Bill Limit ---
            if self.payment_details.shipment_total_value >= 50000:
                has_eway_bill_number = any(bool(eb.strip()) for eb in (self.payment_details.eway_bill_numbers or []))
                has_eway_bill_doc = any(doc.document_type == DocumentType.EWAY_BILL for doc in self.documents)
                if not (has_eway_bill_number or has_eway_bill_doc):
                    raise ValueError("E-Way Bill is mandatory for shipment value >= 50000")

            # --- Rule D: COD Limit ---
            if self.payment_details.is_cod:
                if self.payment_details.cod_amount <= 0:
                    raise ValueError("COD amount must be greater than 0")
                if self.payment_details.cod_amount > self.payment_details.shipment_total_value:
                    raise ValueError("COD amount cannot exceed shipment total value")

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
    appointment_id: Optional[str] = None
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    pickup_strategy: Optional[PickupStrategy] = None

    product_category: ProductCategory
    other_category_description: Optional[str] = None

    reason_for_return: Optional[str] = None
    ndr_reason: Optional[NdrExceptionReason] = None
    created_by_user_id: UUID
    creator_email: Optional[str] = None

    # Nested Objects
    pickup_address: AddressRead
    delivery_address: AddressRead
    packages: List[PackageRead]
    payment_details: Optional[PaymentDetailsRead] = None
    documents: List[PickupDocumentRead] = []

    created_at: datetime


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
    comment: Optional[str] = Field(default=None, max_length=255)  # Reason for change (Required for Status changes)
    is_public: bool = False  # Should this update be visible on the Tracking Page?

    # --- 2. Scheduling & Reference ---
    requested_pickup_date: Optional[date] = None
    order_reference_id: Optional[str] = Field(default=None, max_length=255)
    pickup_time_slot: Optional[PickupTimeSlot] = None
    po_number: Optional[str] = Field(default=None, max_length=255)
    po_date: Optional[date] = None
    appointment_id: Optional[str] = Field(default=None, max_length=100)
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    pickup_strategy: Optional[PickupStrategy] = None

    # --- 3. Cargo Details ---
    product_category: Optional[ProductCategory] = None
    other_category_description: Optional[str] = Field(default=None, max_length=255)

    reason_for_return: Optional[str] = Field(default=None, max_length=255)
    ndr_reason: Optional[NdrExceptionReason] = None

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

    @model_validator(mode="after")
    def validate_business_logic(self) -> "PickupUpdate":
        if getattr(self, "shipment_type", None) == ShipmentType.REVERSE and not self.reason_for_return:
            raise ValueError(
                "reason_for_return is mandatory when shipment_type is REVERSE"
            )

        if self.product_category == ProductCategory.OTHER and not self.other_category_description:
            raise ValueError(
                "other_category_description is required when product_category is OTHER"
            )

        if self.payment_details is not None:
            if self.payment_details.shipment_total_value >= 50000:
                has_eway_bill_number = any(bool(eb.strip()) for eb in (self.payment_details.eway_bill_numbers or []))
                has_eway_bill_doc = any(doc.document_type == DocumentType.EWAY_BILL for doc in (self.documents or []))
                if not (has_eway_bill_number or has_eway_bill_doc):
                    raise ValueError("E-Way Bill is mandatory for shipment value >= 50000")

            if self.payment_details.is_cod:
                if self.payment_details.cod_amount <= 0:
                    raise ValueError("COD amount must be greater than 0")
                if self.payment_details.cod_amount > self.payment_details.shipment_total_value:
                    raise ValueError("COD amount cannot exceed shipment total value")

        return self


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

    tracking_id: str
    status: PickupStatus
    current_location: str = "Processing"  # Placeholder for now
    estimated_delivery: Optional[date] = None
    timeline: List[PublicActivityRead] = []


# --- 6. Pricing & Rate Calculator Schemas ---


class RateCalculationRequest(SQLModel):
    pickup_pincode: str = Field(..., max_length=255)
    delivery_pincode: str = Field(..., max_length=255)
    packages: List[PackageCreate]
    service_type: ServiceType
    is_cod: bool = False
    cod_amount: float = 0.0
    shipment_total_value: float = 0.0
    shipment_type: ShipmentType = ShipmentType.FORWARD
    is_rto: bool = False
    is_b2b: bool = False


class RateCalculationResponse(SQLModel):
    chargeable_weight: float
    base_charge: float
    tax_amount: float
    total_amount: float
    currency: str = "INR"
    estimated_days: int
    pricing_breakdown: dict = {}
    serviceable: bool = True
    error_message: Optional[str] = None


# --- NEW: Bulk Rate Calculation Schemas ---

class QuoteSpecification(SQLModel):
    service_type: ServiceType
    is_rto: bool = False


class BulkRateCalculationRequest(SQLModel):
    pickup_pincode: str = Field(..., max_length=255)
    delivery_pincode: str = Field(..., max_length=255)
    packages: List[PackageCreate]
    is_cod: bool = False
    cod_amount: float = 0.0
    shipment_total_value: float = 0.0
    shipment_type: ShipmentType = ShipmentType.FORWARD
    quotes_to_calculate: Optional[List[QuoteSpecification]] = None
    is_b2b: bool = False


class ServiceQuote(SQLModel):
    service_type: ServiceType
    is_rto: bool = False
    serviceable: bool
    quote: Optional[RateCalculationResponse] = None
    error_message: Optional[str] = None


class BulkRateCalculationResponse(SQLModel):
    quotes: List[ServiceQuote]

