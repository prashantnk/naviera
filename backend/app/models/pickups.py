import uuid
from typing import Optional, List
from datetime import date, datetime
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship

# --- 1. Enums (The Rules) ---

class ShipmentType(str, Enum):
    FORWARD = "FORWARD"
    REVERSE = "REVERSE"

class ServiceType(str, Enum):
    SURFACE = "SURFACE"
    EXPRESS = "EXPRESS"

class PaymentMode(str, Enum):
    PREPAID = "PREPAID"
    COD = "COD"

class PickupStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RTO_INITIATED = "RTO_INITIATED"

class DocumentType(str, Enum):
    # Core Compliance
    GST_INVOICE = "GST_INVOICE"
    EWAY_BILL = "EWAY_BILL"            # Mandatory if > 50k
    DELIVERY_CHALLAN = "DELIVERY_CHALLAN"
    DECLARATION = "DECLARATION"        # For gifts/personal items
    
    # Evidence / Operations
    BOX_PHOTO = "BOX_PHOTO"            # Proof of condition
    LABEL_IMAGE = "LABEL_IMAGE"        # If user provides their own label
    OTHER = "OTHER"


# --- 2. Modular Tables ---

class Address(SQLModel, table=True):
    """
    Physical locations (Sender/Receiver).
    """
    __tablename__ = "addresses" # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    
    name: str = Field(max_length=100)
    phone: str = Field(max_length=20, nullable=False)
    email: Optional[str] = Field(default=None, max_length=100)
    company_name: Optional[str] = Field(default=None, max_length=100)
    
    address_line1: str
    address_line2: Optional[str] = None
    landmark: Optional[str] = None
    city: str = Field(index=True, max_length=50)
    state: str = Field(max_length=50)
    pincode: str = Field(index=True, min_length=6, max_length=10, nullable=False)
    country: str = Field(default="IN", max_length=2)


class PickupDocument(SQLModel, table=True):
    """
    Stores file references. 1 Pickup = Many Documents.
    Allows multiple photos, invoice + eway bill, etc.
    """
    __tablename__ = "pickup_documents" # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pickup_id: uuid.UUID = Field(foreign_key="pickups.id", nullable=False)
    
    document_type: DocumentType = Field(nullable=False)
    file_url: str = Field(description="S3/Storage URL")
    file_name: str = Field(description="Original filename")
    
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationship
    pickup: "PickupRequest" = Relationship(back_populates="documents")


class PaymentDetails(SQLModel, table=True):
    """
    Financials & Compliance Info.
    """
    __tablename__ = "payment_details" # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pickup_id: uuid.UUID = Field(foreign_key="pickups.id", nullable=False)
    
    amount: float = Field(default=0.0)
    currency: str = Field(default="INR", max_length=3)
    payment_mode: PaymentMode = Field(default=PaymentMode.PREPAID)
    
    # Tax & Compliance
    declared_value: float = Field(default=0.0, description="Total shipment value")
    tax_amount: float = Field(default=0.0)
    hsn_code: Optional[str] = Field(default=None, description="Harmonized System Nomenclature")
    
    # We store the *Numbers* here for search, but the *Files* go in PickupDocument
    invoice_number: Optional[str] = Field(default=None)
    invoice_date: Optional[date] = None
    eway_bill_number: Optional[str] = None 

    pickup: "PickupRequest" = Relationship(back_populates="payment_details")


class PackageDetails(SQLModel, table=True):
    """
    Physical Box Dimensions.
    """
    __tablename__ = "package_details" # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pickup_id: uuid.UUID = Field(foreign_key="pickups.id", nullable=False)
    
    length: float = Field(description="CM")
    breadth: float = Field(description="CM")
    height: float = Field(description="CM")
    weight: float = Field(description="KG")
    
    box_count: int = Field(default=1)
    description: Optional[str] = Field(default=None, description="Specifics for this box")
    is_fragile: bool = Field(default=False)
    
    pickup: "PickupRequest" = Relationship(back_populates="packages")


# --- 3. The Main Shipment Table ---

class PickupRequest(SQLModel, table=True):
    __tablename__ = "pickups" # type: ignore

    # Identity
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    created_by_user_id: uuid.UUID = Field(nullable=False)

    # Reference
    order_reference_id: str = Field(index=True, max_length=100)
    tracking_id: Optional[str] = Field(default=None, index=True)

    # Shipment Overview (From Screenshot)
    shipment_type: ShipmentType = Field(default=ShipmentType.FORWARD)
    service_type: ServiceType = Field(default=ServiceType.SURFACE)
    status: PickupStatus = Field(default=PickupStatus.DRAFT)
    
    # The "Shipment Details" section from UI
    product_category: Optional[str] = Field(default=None, description="e.g. Electronics, Clothing")
    shipment_description: Optional[str] = Field(default=None, description="General description of goods")
    
    # Return Logic
    reason_for_return: Optional[str] = Field(default=None, description="Mandatory if Type is REVERSE")

    # Scheduling
    requested_pickup_date: date = Field(nullable=False)

    # Foreign Keys
    pickup_address_id: uuid.UUID = Field(foreign_key="addresses.id")
    delivery_address_id: uuid.UUID = Field(foreign_key="addresses.id")

    # Relationships
    packages: List[PackageDetails] = Relationship(back_populates="pickup")
    documents: List[PickupDocument] = Relationship(back_populates="pickup")
    
    payment_details: Optional[PaymentDetails] = Relationship(
        sa_relationship_kwargs={"uselist": False},
        back_populates="pickup"
    )
    
    # Address Loading
    pickup_address: Address = Relationship(
        sa_relationship_kwargs={"primaryjoin": "PickupRequest.pickup_address_id==Address.id"}
    )
    delivery_address: Address = Relationship(
        sa_relationship_kwargs={"primaryjoin": "PickupRequest.delivery_address_id==Address.id"}
    )

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)