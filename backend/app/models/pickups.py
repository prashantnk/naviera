import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlalchemy import Enum as sa_Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import JSON, Column, Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.manifests import Manifest

FREIGHT_COLLECTIBLE_DEFAULT = Decimal("0.00")
"""Default of `payment_details.freight_collectible` (server default 0, migration M-B3)."""

# --- 1. Enums (The Rules) ---


class AddressCategory(str, Enum):
    HOME = "HOME"
    OFFICE = "OFFICE"
    WAREHOUSE = "WAREHOUSE"
    STOREFRONT = "STOREFRONT"
    OTHER = "OTHER"


class AddressScope(str, Enum):
    PRIVATE = "PRIVATE"
    TENANT = "TENANT"


class DimensionUnit(str, Enum):
    CM = "CM"
    M = "M"
    IN = "IN"
    FT = "FT"


class WeightUnit(str, Enum):
    KG = "KG"
    G = "G"


class ShipmentType(str, Enum):
    FORWARD = "FORWARD"
    REVERSE = "REVERSE"


class ServiceType(str, Enum):
    SURFACE_ROAD = "SURFACE_ROAD"
    SURFACE_TRAIN = "SURFACE_TRAIN"
    AIR = "AIR"


class ServiceOption(str, Enum):
    """
    The carrier service a shipment is booked on (carrier × mode × rate source, M-P1).
    Stored as VARCHAR(40) + CHECK `ck_pickups_service_option_valid`; a new option is a
    CHECK swap, never an enum DDL migration.
    DELHIVERY_SURFACE / DELHIVERY_EXPRESS are B2C parcels priced live by Delhivery's
    Express API; PRIME_SURFACE is B2B cargo priced from Logismart's Prime rate table;
    DELHIVERY_B2B_SURFACE is B2B cargo (LTL) priced live by Delhivery's B2B freight
    estimate API (M-P3 adds it to the CHECK).
    """

    DELHIVERY_SURFACE = "DELHIVERY_SURFACE"
    DELHIVERY_EXPRESS = "DELHIVERY_EXPRESS"
    PRIME_SURFACE = "PRIME_SURFACE"
    DELHIVERY_B2B_SURFACE = "DELHIVERY_B2B_SURFACE"


SERVICE_OPTION_MAX_LENGTH = 40
"""Width of `pickups.service_option` (VARCHAR(40))."""

CARRIER_AWB_MAX_LENGTH = 40
"""Width of `pickups.carrier_awb` (VARCHAR(40))."""


class FreightPaymentMode(str, Enum):
    PREPAID = "PREPAID"
    POSTPAID = "POSTPAID"
    TO_PAY = "TO_PAY"


class CodRemittanceStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_COLLECTION = "PENDING_COLLECTION"
    COLLECTED = "COLLECTED"
    REMITTED = "REMITTED"
    FAILED_RTO = "FAILED_RTO"


class PickupStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    EXCEPTION = "EXCEPTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RTO_INITIATED = "RTO_INITIATED"
    RTO_IN_TRANSIT = "RTO_IN_TRANSIT"
    RTO_DELIVERED = "RTO_DELIVERED"
    QC_FAILED = "QC_FAILED"
    REJECTED_AT_PICKUP = "REJECTED_AT_PICKUP"
    LOST = "LOST"


class NdrExceptionReason(str, Enum):
    """
    Why a shipment is on hold (Delhivery One "Exceptions & NDR" parity).
    CUSTOMER_UNAVAILABLE is the legacy label of CONSIGNEE_UNAVAILABLE; both are
    treated identically by the allowed-actions matrix (`services/ndr_rules.py`).
    """

    DOCUMENT_NEEDED = "DOCUMENT_NEEDED"
    APPOINTMENT_NEEDED = "APPOINTMENT_NEEDED"
    SHORT_SHIPMENT = "SHORT_SHIPMENT"
    CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE"
    PAYMENT_DISPUTE = "PAYMENT_DISPUTE"
    DAMAGED = "DAMAGED"
    EWAY_BILL_MISSING = "EWAY_BILL_MISSING"
    CONSIGNEE_DETAILS_REQUIRED = "CONSIGNEE_DETAILS_REQUIRED"
    CONSIGNEE_REFUSED = "CONSIGNEE_REFUSED"
    CONSIGNEE_UNAVAILABLE = "CONSIGNEE_UNAVAILABLE"
    DELIVERY_RESCHEDULED = "DELIVERY_RESCHEDULED"
    FREIGHT_COLLECTION = "FREIGHT_COLLECTION"
    ADDITIONAL_CHARGES = "ADDITIONAL_CHARGES"
    WEIGHT_DISCREPANCY = "WEIGHT_DISCREPANCY"
    PICKUP_FAILED = "PICKUP_FAILED"


class NdrAction(str, Enum):
    """
    The merchant's response to an exception. Which actions are allowed for a
    given shipment is decided server-side by the allowed-actions matrix.
    Spring Boot Equivalent: an '@Enumerated(EnumType.STRING)' command type.
    """

    REATTEMPT = "REATTEMPT"
    RETURN_TO_ORIGIN = "RETURN_TO_ORIGIN"
    UPDATE_CONSIGNEE = "UPDATE_CONSIGNEE"
    UPDATE_PAYMENT_MODE = "UPDATE_PAYMENT_MODE"
    UPDATE_EWAY_BILL = "UPDATE_EWAY_BILL"
    UPLOAD_DOCUMENT = "UPLOAD_DOCUMENT"
    BOOK_APPOINTMENT = "BOOK_APPOINTMENT"
    DELIVER_WITHOUT_APPOINTMENT = "DELIVER_WITHOUT_APPOINTMENT"
    PARTIAL_DELIVERY = "PARTIAL_DELIVERY"
    HOLD = "HOLD"
    REPACK_AND_DELIVER = "REPACK_AND_DELIVER"
    ACKNOWLEDGE_CHARGES = "ACKNOWLEDGE_CHARGES"
    ACCEPT_WEIGHT = "ACCEPT_WEIGHT"
    DISPUTE_WEIGHT = "DISPUTE_WEIGHT"
    RESCHEDULE_PICKUP = "RESCHEDULE_PICKUP"
    CANCEL_PICKUP = "CANCEL_PICKUP"


class DocumentType(str, Enum):
    # Core Compliance
    GST_INVOICE = "GST_INVOICE"
    EWAY_BILL = "EWAY_BILL"  # Mandatory if > 50k
    DELIVERY_CHALLAN = "DELIVERY_CHALLAN"
    DECLARATION = "DECLARATION"  # For gifts/personal items

    # Evidence / Operations
    BOX_PHOTO = "BOX_PHOTO"  # Proof of condition
    LABEL_IMAGE = "LABEL_IMAGE"  # If user provides their own label
    OTHER = "OTHER"

    # B2B Support
    PO_COPY = "PO_COPY"
    KYC = "KYC"
    REGULATORY_FORM = "REGULATORY_FORM"
    PHOTO_ID = "PHOTO_ID"
    ASN = "ASN"
    E_INVOICE_QR = "E_INVOICE_QR"


class ActivityType(str, Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    INFO_UPDATE = "INFO_UPDATE"  # Address, Package details changed
    COMMENT = "COMMENT"  # Just a note, no data change
    EXCEPTION = "EXCEPTION"  # Delivery Attempt Failed, etc.


class PickupTimeSlot(str, Enum):
    MORNING_06_10 = "06:00 - 10:00"
    MIDDAY_10_14 = "10:00 - 14:00"
    AFTERNOON_14_18 = "14:00 - 18:00"
    EVENING_18_22 = "18:00 - 22:00"


class ProductCategory(str, Enum):
    HOUSEHOLD_PERSONAL = "HOUSEHOLD_PERSONAL"
    VEHICLE = "VEHICLE"
    DOCUMENTS = "DOCUMENTS"
    HAZARDOUS = "HAZARDOUS"
    COMMERCIAL = "COMMERCIAL"
    ELECTRONICS = "ELECTRONICS"
    APPAREL = "APPAREL"
    OTHER = "OTHER"


class PickupStrategy(str, Enum):
    DEFAULT = "DEFAULT"
    DEDICATED = "DEDICATED"
    CONSOLIDATED = "CONSOLIDATED"


# --- 2. Modular Tables ---


class Address(SQLModel, table=True):
    """
    Physical locations (Sender/Receiver).
    """

    __tablename__ = "addresses"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)

    user_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="user.id", index=True
    )
    category: AddressCategory = Field(
        default=AddressCategory.HOME,
        sa_column=Column(sa_Enum(AddressCategory, name="addresscategory"), nullable=False)
    )
    scope: AddressScope = Field(
        default=AddressScope.PRIVATE,
        sa_column=Column(sa_Enum(AddressScope, name="addressscope"), nullable=False)
    )
    alternate_phone: Optional[str] = Field(default=None, max_length=20)
    gstin: Optional[str] = Field(default=None, max_length=15)
    address_signature: Optional[str] = Field(default=None, index=True)
    is_saved: bool = Field(default=False, index=True)

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

    __tablename__ = "pickup_documents"  # type: ignore

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

    __tablename__ = "payment_details"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pickup_id: uuid.UUID = Field(foreign_key="pickups.id", nullable=False)

    currency: str = Field(default="INR", max_length=3, description="ISO Currency code for all transactions.")
    
    freight_payment_mode: FreightPaymentMode = Field(
        default=FreightPaymentMode.PREPAID,
        sa_column=Column(sa_Enum(FreightPaymentMode, name="freightpaymentmode"), nullable=False),
        description="Specifies who settles the logistics/shipping invoice (Prepaid, Postpaid, or To Pay at delivery)."
    )
    is_cod: bool = Field(
        default=False,
        description="Toggle to collect cash for the item value from the receiver at delivery."
    )
    cod_amount: float = Field(
        default=0.0,
        description="Item/Cargo commercial value to collect from the receiver at door. Billed independently of freight."
    )
    add_shipping_to_cod: bool = Field(
        default=False,
        description="Toggle to collect dynamic shipping charges from the receiver as part of COD doorstep payment."
    )
    cod_remittance_status: CodRemittanceStatus = Field(
        default=CodRemittanceStatus.NOT_APPLICABLE,
        sa_column=Column(sa_Enum(CodRemittanceStatus, name="codremittancestatus"), nullable=False),
        description="Fintech reconciliation workflow tracking status of cash collected at delivery."
    )

    # Pricing Ledger
    base_freight: float = Field(
        default=0.0,
        description="Core transportation service charge before taxes or auxiliary surcharges."
    )
    tax_amount: float = Field(
        default=0.0,
        description="GST/VAT indirect taxation levied on the logistics service fee."
    )
    total_logistics_cost: float = Field(
        default=0.0,
        description="Total shipping charge including base freight, taxes, and dynamic surcharges."
    )

    # JSON Audit Ledger
    pricing_breakdown: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Raw audited schema logs recording the dynamic pricing engine's step-by-step calculations. Holds all dynamic surcharges such as cod_fee, fuel_surcharge, and network_surcharge."
    )

    # Tax & Compliance
    shipment_value: float = Field(
        default=0.0,
        ge=0,
        description="Base commercial value of the cargo inside packages."
    )
    shipment_tax_value: float = Field(
        default=0.0,
        ge=0,
        description="Commercial tax levied on the cargo (e.g., product sales tax)."
    )
    shipment_total_value: float = Field(
        default=0.0,
        ge=0,
        description="Total value of the commercial shipment (Shipment Value + Tax Value)."
    )
    hsn_code: Optional[str] = Field(
        default=None, description="Harmonized System Nomenclature"
    )

    # We store the *Numbers* here for search, but the *Files* go in PickupDocument
    invoice_numbers: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    invoice_date: Optional[date] = None
    eway_bill_numbers: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))

    chargeable_weight: float = Field(default=0.0, description="Weight used for billing calculation")

    # Migration M-B3 (5b3c9d4eaf03): exact NUMERIC(12,2) money, read through core/money.to_money().
    freight_collectible: Decimal = Field(
        default=FREIGHT_COLLECTIBLE_DEFAULT,
        sa_column=Column(
            sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")
        ),
        description="TO_PAY freight the rider still has to collect at the door (falls when the merchant pays it via Freight Collection).",
    )

    # Migration M-P1 (9a1b2c3d4e5f): SERVER-ONLY carrier cost (what Delhivery / the Prime
    # transporter charges Logismart + the inputs used). Never on a read schema.
    carrier_cost: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
        description="Server-only carrier cost record (pricing redesign D2); never serialised.",
    )

    pickup: "PickupRequest" = Relationship(back_populates="payment_details")


class PackageDetails(SQLModel, table=True):
    """
    Physical Box Dimensions.
    """

    __tablename__ = "package_details"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pickup_id: uuid.UUID = Field(foreign_key="pickups.id", nullable=False)

    length: float = Field(description="Length")
    breadth: float = Field(description="Breadth")
    height: float = Field(description="Height")
    dimension_unit: DimensionUnit = Field(
        default=DimensionUnit.CM,
        sa_column=Column(sa_Enum(DimensionUnit, name="dimensionunit"), nullable=False)
    )
    weight: float = Field(description="Weight")
    weight_unit: WeightUnit = Field(
        default=WeightUnit.KG,
        sa_column=Column(sa_Enum(WeightUnit, name="weightunit"), nullable=False)
    )

    box_count: int = Field(default=1)
    description: Optional[str] = Field(
        default=None, description="Specifics for this box"
    )
    is_fragile: bool = Field(default=False)
    child_awb_number: Optional[str] = Field(default=None, max_length=100)

    pickup: "PickupRequest" = Relationship(back_populates="packages")


# --- 3. The Main Shipment Table ---


class PickupRequest(SQLModel, table=True):
    __tablename__ = "pickups"  # type: ignore

    # Identity
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    created_by_user_id: uuid.UUID = Field(nullable=False)

    # Reference
    order_reference_id: Optional[str] = Field(default=None, index=True, max_length=100)
    tracking_id: Optional[str] = Field(default=None, index=True)

    # Shipment Overview (From Screenshot)
    shipment_type: ShipmentType = Field(default=ShipmentType.FORWARD)
    service_type: ServiceType = Field(default=ServiceType.SURFACE_ROAD)
    # Migration M-P1 (9a1b2c3d4e5f): the booked carrier service; `service_type` is derived from it.
    service_option: ServiceOption = Field(
        default=ServiceOption.DELHIVERY_SURFACE,
        sa_column=Column(
            sa_Enum(
                ServiceOption,
                name="serviceoption",
                native_enum=False,
                create_constraint=False,
                length=SERVICE_OPTION_MAX_LENGTH,
            ),
            nullable=False,
        ),
    )
    # Migration M-P1: the carrier's own AWB that ops paste in (unique per tenant when set).
    carrier_awb: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.String(CARRIER_AWB_MAX_LENGTH), nullable=True),
    )
    status: PickupStatus = Field(default=PickupStatus.DRAFT)

    latest_status_comment: Optional[str] = Field(default=None)
    pickup_time_slot: Optional[PickupTimeSlot] = Field(
        default=None,
        sa_column=Column(
            sa_Enum(PickupTimeSlot, name="pickuptimeslot"),
            nullable=True,
        ),
    )

    # The "Shipment Details" section from UI
    product_category: ProductCategory = Field(
        sa_column=Column(
            sa_Enum(ProductCategory, name="productcategory"),
            nullable=False,
        ),
    )
    other_category_description: Optional[str] = Field(
        default=None,
        description="Custom product category description if OTHER is selected",
    )


    # Return Logic
    reason_for_return: Optional[str] = Field(
        default=None, description="Mandatory if Type is REVERSE"
    )

    # Reverse Logistics Doorstep Quality Check (QC) — Prevents E-Commerce & B2B Return Fraud
    # Real-World Use Case: When a customer returns a high-value item (e.g., iPhone or car battery),
    # 'qc_required=True' prompts the pickup rider with 'qc_notes' (IMEI/seal check) at the doorstep.
    # If the item fails inspection, the rider rejects it at the door ('QC_FAILED' / 'REJECTED_AT_PICKUP').
    qc_required: bool = Field(
        default=False,
        sa_column=sa.Column(sa.Boolean, nullable=False, server_default=sa.text("false")),
        description="Whether a doorstep quality check (QC) is required at pickup (for REVERSE return shipments)"
    )
    qc_notes: Optional[str] = Field(
        default=None,
        description="Step-by-step inspection checklist for the pickup executive (e.g., verify serial number & unbroken seal)"
    )

    ndr_reason: Optional[NdrExceptionReason] = Field(
        default=None,
        sa_column=Column(
            sa_Enum(NdrExceptionReason, name="ndrexceptionreason", create_type=True),
            nullable=True,
        )
    )
    # NDR bookkeeping (Delhivery parity): failed delivery / pickup attempts,
    # the last field-agent remark, when the current exception was raised (for
    # server-side aging) and the charge ops entered (freight collection,
    # additional charges or weight delta) that the merchant must acknowledge.
    ndr_attempt_count: int = Field(
        default=0,
        sa_column=sa.Column(sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    ndr_remark: Optional[str] = Field(default=None, max_length=255)
    exception_raised_at: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=False), nullable=True),
    )
    charge_amount: Optional[float] = Field(
        default=None,
        sa_column=sa.Column(sa.Numeric(12, 2, asdecimal=False), nullable=True),
    )
    # Migration M-B3 (5b3c9d4eaf03): boxes actually handed over on a Short Shipment
    # partial delivery (NULL = not a partial delivery; CHECK >= 0 in the DB).
    delivered_box_count: Optional[int] = Field(
        default=None,
        sa_column=sa.Column(sa.Integer, nullable=True),
    )

    # Scheduling
    requested_pickup_date: date = Field(nullable=False)

    # Foreign Keys
    pickup_address_id: uuid.UUID = Field(foreign_key="addresses.id")
    delivery_address_id: uuid.UUID = Field(foreign_key="addresses.id")

    # Fleet Pickup / Truck Run-Sheet Linkage ('manifests.id' with ON DELETE SET NULL)
    # Real-World Use Case: Links multiple B2B LRs ('pickups') to one scheduled truck ('Manifest').
    # Uses 'ondelete="SET NULL"' so if a truck manifest is cancelled or deleted, the customer's paid
    # shipments are never cascade-deleted—they safely detach ('manifest_id = None') and return to 'OPEN'.
    manifest_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=sa.Column(
            sa.Uuid,
            sa.ForeignKey("manifests.id", ondelete="SET NULL"),
            nullable=True
        ),
        description="Optional parent Fleet Manifest (Run-Sheet) ID; SET NULL on manifest cancellation/deletion"
    )

    # Relationships
    packages: List[PackageDetails] = Relationship(back_populates="pickup")
    documents: List[PickupDocument] = Relationship(back_populates="pickup")

    payment_details: Optional[PaymentDetails] = Relationship(
        sa_relationship_kwargs={"uselist": False}, back_populates="pickup"
    )

    activities: List["ShipmentActivity"] = Relationship(back_populates="pickup")
    manifest: Optional["Manifest"] = Relationship(back_populates="pickups")

    # Address Loading
    pickup_address: Address = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "PickupRequest.pickup_address_id==Address.id"
        }
    )
    delivery_address: Address = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "PickupRequest.delivery_address_id==Address.id"
        }
    )

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Enterprise B2B Purchase Order (PO) Details
    # Real-World Use Case: Large retail warehouses (Reliance Retail, Amazon FBA, DMart) reject trucks at
    # the gate if the supplier's PO has expired ('po_expiry_date').
    po_number: Optional[str] = Field(default=None, max_length=255)
    po_date: Optional[date] = Field(default=None)
    po_expiry_date: Optional[date] = Field(
        default=None,
        description="Enterprise consignee Purchase Order (PO) cutoff date after which dock delivery is rejected"
    )

    # Appointment Slots
    appointment_id: Optional[str] = Field(default=None, max_length=100)
    appointment_start: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True)
    )
    appointment_end: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True)
    )

    # Pickup Strategy
    pickup_strategy: Optional[PickupStrategy] = Field(
        default=None,
        sa_column=Column(
            sa_Enum(PickupStrategy, name="pickupstrategy"),
            nullable=True,
        )
    )

    # B2B Heavy Cargo Operational Flags (Dock Blind Pickups & FOV Transit Insurance)
    # 1. 'is_blind_pickup' + 'estimated_box_count': Allows factory staff to dispatch N cartons on a truck
    #    without measuring LxWxH at the loading dock; true weight is billed later at the Hub DWS laser scale.
    # 2. 'is_carriers_risk': Toggles Owner's Risk (False -> ₹0 surcharge, shipper's own insurance) vs
    #    Carrier's Risk (True -> Logismart assumes damage liability and bills 'b2b_fov_percent' FOV fee).
    is_blind_pickup: bool = Field(
        default=False,
        sa_column=sa.Column(sa.Boolean, nullable=False, server_default=sa.text("false")),
        description="Toggle to hide package dimensions and default weight for blind factory dock pickups"
    )
    estimated_box_count: Optional[int] = Field(
        default=None,
        nullable=True,
        description="Mandatory carton count estimate when is_blind_pickup is True so hub dispatches right truck size"
    )
    is_carriers_risk: bool = Field(
        default=False,
        sa_column=sa.Column(sa.Boolean, nullable=False, server_default=sa.text("false")),
        description="True = Carrier's Risk (adds FOV surcharge); False = Owner's Risk (₹0 insurance fee)"
    )

    # Last-Mile 6-Digit OTP Proof of Delivery (POD) — Eliminates Fake Delivery Disputes
    # Real-World Use Case: Generated automatically when status transitions to 'IN_TRANSIT'.
    # Field driver cannot mark shipment 'COMPLETED' without entering the consignee's 6-digit 'delivery_otp'
    # and capturing 'pod_received_by' (name/designation of the person who accepted the cargo).
    delivery_otp: Optional[str] = Field(
        default=None,
        max_length=6,
        description="6-digit secret OTP generated on IN_TRANSIT; mandatory to transition shipment to COMPLETED"
    )
    pod_received_by: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Full name / designation of the consignee representative who provided the OTP at delivery"
    )


class ShipmentActivity(SQLModel, table=True):
    """
    The Immutable Ledger of everything that happens to a shipment.
    Tracks: Who, What, When, Why, and Visibility.
    """

    __tablename__ = "shipment_activities"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pickup_id: uuid.UUID = Field(foreign_key="pickups.id", nullable=False)

    # THE ACTOR (Who did it?)
    user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)

    timestamp: datetime = Field(default_factory=datetime.utcnow)

    activity_type: ActivityType = Field(default=ActivityType.INFO_UPDATE)

    # VISIBILITY (User Requirement)
    # True = Show on public tracking page. False = Internal Log.
    is_public: bool = Field(default=False)

    # THE WHAT (System Generated Summary)
    summary: Optional[str] = None

    # THE WHY (User Comment)
    comment: Optional[str] = None

    # THE DIFF (Technical Payload)
    # Stores: { "field_name": { "old": "val", "new": "val" }, "packages": {...} }
    diff: dict = Field(default={}, sa_column=Column(JSON))

    # Relationships
    pickup: PickupRequest = Relationship(back_populates="activities")
