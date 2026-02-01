from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import EmailStr, model_validator
from sqlmodel import Field, SQLModel  # Using SQLModel for consistency

# Import Enums
from app.models.pickups import (
    AddressType,
    DocumentType,
    PaymentMode,
    PickupStatus,
    ServiceType,
    ShipmentType,
)

# --- 1. Base Building Blocks ---


class AddressBase(SQLModel):
    name: str
    phone: str
    email: Optional[EmailStr] = None
    company_name: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    landmark: Optional[str] = None
    city: str
    state: str
    pincode: str
    country: str = "IN"
    address_type: AddressType = AddressType.CUSTOMER
    is_saved: bool = (
        False  # default to transient addresses (Not treated as saved to DB)
    )


class PackageBase(SQLModel):
    length: float = Field(gt=0, description="Length in CM")
    breadth: float = Field(gt=0, description="Breadth in CM")
    height: float = Field(gt=0, description="Height in CM")
    weight: float = Field(gt=0, description="Weight in KG")
    box_count: int = Field(default=1, gt=0)
    description: Optional[str] = None
    is_fragile: bool = False


class PaymentDetailsBase(SQLModel):
    amount: float = Field(default=0.0, ge=0)
    currency: str = "INR"
    payment_mode: PaymentMode = PaymentMode.PREPAID
    declared_value: float = Field(default=0.0, ge=0)
    tax_amount: float = 0.0
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

    order_reference_id: str
    shipment_type: ShipmentType = ShipmentType.FORWARD
    service_type: ServiceType = ServiceType.SURFACE
    requested_pickup_date: date

    product_category: Optional[str] = None
    shipment_description: Optional[str] = None
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

        # --- Rule 3: Anti-Pollution (Security) ---
        # Users should not define global Warehouses in this transient flow.
        if (
            self.new_pickup_address
            and self.new_pickup_address.address_type == AddressType.WAREHOUSE
        ):
            raise ValueError(
                "You cannot create a WAREHOUSE address here. Please use the Settings page."
            )

        if (
            self.new_delivery_address
            and self.new_delivery_address.address_type == AddressType.WAREHOUSE
        ):
            raise ValueError(
                "You cannot create a WAREHOUSE address here. Please use the Settings page."
            )

        return self


# --- 3. Read Schemas (Outputs) ---


class AddressRead(AddressBase):
    id: UUID


class PackageRead(PackageBase):
    id: UUID


class PaymentDetailsRead(PaymentDetailsBase):
    id: UUID


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
    order_reference_id: str
    shipment_type: ShipmentType
    service_type: ServiceType
    requested_pickup_date: date

    # Nested Objects
    pickup_address: AddressRead
    delivery_address: AddressRead
    packages: List[PackageRead]
    payment_details: Optional[PaymentDetailsRead] = None
    documents: List[PickupDocumentRead] = []

    created_at: datetime
