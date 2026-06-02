from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import EmailStr, model_validator
from sqlmodel import Field, SQLModel  # Using SQLModel for consistency

# Import Enums
from app.models.pickups import (
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
)

# --- 1. Base Building Blocks ---


class AddressBase(SQLModel):
    name: str
    phone: str
    alternate_phone: Optional[str] = None
    email: Optional[EmailStr] = None
    company_name: Optional[str] = None
    gstin: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    landmark: Optional[str] = None
    city: str
    state: str
    pincode: str
    country: str = "IN"
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
    description: Optional[str] = None
    is_fragile: bool = False


class PaymentDetailsBase(SQLModel):
    currency: str = "INR"
    
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
    hsn_code: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    eway_bill_number: Optional[str] = None



# --- NEW: Document Schema ---
class PickupDocumentBase(SQLModel):
    document_type: DocumentType
    file_url: str
    file_name: str


# --- 2. Create Schemas (Inputs) ---


class AddressCreate(AddressBase):
    pass

class AddressUpdate(SQLModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    gstin: Optional[str] = None
    email: Optional[EmailStr] = None
    company_name: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    landmark: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
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

    order_reference_id: Optional[str] = None
    shipment_type: ShipmentType = ShipmentType.FORWARD
    service_type: ServiceType = ServiceType.SURFACE_ROAD
    requested_pickup_date: date
    pickup_time_slot: PickupTimeSlot

    product_category: ProductCategory
    other_category_description: Optional[str] = None

    reason_for_return: Optional[str] = None

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

    product_category: ProductCategory
    other_category_description: Optional[str] = None

    reason_for_return: Optional[str] = None
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
    comment: Optional[str] = None  # Reason for change (Required for Status changes)
    is_public: bool = False  # Should this update be visible on the Tracking Page?

    # --- 2. Scheduling & Reference ---
    requested_pickup_date: Optional[date] = None
    order_reference_id: Optional[str] = None
    pickup_time_slot: Optional[PickupTimeSlot] = None

    # --- 3. Cargo Details ---
    product_category: Optional[ProductCategory] = None
    other_category_description: Optional[str] = None

    reason_for_return: Optional[str] = None

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
    pickup_pincode: str
    delivery_pincode: str
    packages: List[PackageCreate]
    service_type: ServiceType
    is_cod: bool = False
    shipment_total_value: float = 0.0


class RateCalculationResponse(SQLModel):
    chargeable_weight: float
    base_charge: float
    tax_amount: float
    total_amount: float
    currency: str = "INR"
    estimated_days: int
    pricing_breakdown: dict = {}
