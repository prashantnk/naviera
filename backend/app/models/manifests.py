import uuid
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlalchemy import Enum as sa_Enum
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.pickups import PickupRequest

PICKUP_REQUEST_NUMBER_INDEX = "uq_manifests_tenant_pickup_request_number"


class ManifestStatus(str, Enum):
    """
    Pickup Request (PUR) / Truck Dispatch Lifecycle ('manifests' table):
    - SCHEDULED: Warehouse booked a pickup slot (e.g., 4:00 PM - 6:00 PM) and linked OPEN shipments.
    - OUT_FOR_PICKUP: Logismart hub assigned a vehicle/driver and dispatched it to the warehouse dock.
    - PICKED: Driver physically loaded the cartons at the dock and signed the Run-Sheet PDF.
    - CANCELED: Booking cancelled; linked shipments automatically detach ('manifest_id = None') and revert to 'OPEN'.
    - NOT_PICKED: Pickup attempt failed (reason in 'failure_reason'); linked shipments detach and revert to 'OPEN'.
    """

    SCHEDULED = "SCHEDULED"
    OUT_FOR_PICKUP = "OUT_FOR_PICKUP"
    PICKED = "PICKED"
    CANCELED = "CANCELED"
    NOT_PICKED = "NOT_PICKED"


class ServiceFlow(str, Enum):
    """
    Which product flow a Pickup Request belongs to (Delhivery One 'Domestic' vs 'B2B Surface').
    Stored as VARCHAR(8) so new flows never need an enum DDL migration.
    Spring Boot Equivalent: '@Enumerated(EnumType.STRING) ServiceFlow serviceFlow'.
    """

    B2C = "B2C"
    B2B = "B2B"


class Manifest(SQLModel, table=True):
    """
    B2B Fleet Pickup / Truck Handover Run-Sheet ('manifests' table).

    Real-World Warehouse & Logistics Use Case:
    - Decouples individual customer orders / Lorry Receipts ('PickupRequest' in 'pickups') from the
      physical truck dispatch ('Manifest').
    - Example: A Surat or Mumbai distributor generates 8 separate B2B LRs throughout the morning for 8
      different cities. Instead of 8 small courier vans arriving at their loading dock, they group all
      8 'OPEN' LRs into a single 'Manifest' (Run-Sheet) for one 14-ft Eicher truck arriving at 4:00 PM.
    - Also supports 'Blind Pickups' ('is_blind_pickup = True'), where a factory dispatches a truckload
      of N cartons ('total_boxes') without measuring box dimensions until the truck reaches the hub's
      DWS (Dimension-Weight-Scanning) laser scale.
    - Spring Boot / JPA Equivalent: '@Entity @Table(name = "manifests")' with '@OneToMany(mappedBy = "manifest") List<PickupRequest> pickups'.
    """

    __tablename__ = "manifests"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        index=True,
        nullable=False,
        description="Multi-tenant isolation key ensuring warehouses only see their own tenant's fleet manifests",
    )
    pickup_address_id: uuid.UUID = Field(
        foreign_key="addresses.id",
        nullable=False,
        description="Origin warehouse / factory loading dock address where the truck must arrive",
    )

    status: ManifestStatus = Field(
        default=ManifestStatus.SCHEDULED,
        sa_column=sa.Column(
            sa_Enum(ManifestStatus, name="manifeststatus"), nullable=False
        ),
        description="Current truck dispatch state (SCHEDULED -> OUT_FOR_PICKUP -> PICKED / CANCELED)",
    )
    scheduled_date: date = Field(
        nullable=False,
        description="Calendar date when the truck is scheduled to arrive at the warehouse dock",
    )
    time_slot: str = Field(
        nullable=False,
        description="Dock arrival time window (e.g., '10:00 AM - 02:00 PM' or '02:00 PM - 06:00 PM')",
    )
    is_blind_pickup: bool = Field(
        default=False,
        nullable=False,
        description="True when the truck is booked for bulk unmeasured cartons (weighed later at the Hub DWS scale)",
    )
    total_boxes: int = Field(
        default=0,
        nullable=False,
        description="Aggregate master carton count across all linked LRs (or estimated cartons for Blind Pickups)",
    )
    created_at: date = Field(
        default_factory=date.today,
        sa_column=sa.Column(
            sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")
        ),
        description="Audit date when the warehouse placed the truck booking (distinct from scheduled_date for SLA tracking)",
    )
    service_flow: ServiceFlow = Field(
        default=ServiceFlow.B2B,
        sa_column=sa.Column(
            sa_Enum(
                ServiceFlow,
                name="serviceflow",
                native_enum=False,
                create_constraint=False,
                length=8,
            ),
            nullable=False,
            server_default=ServiceFlow.B2B.value,
        ),
        description="Product flow of this Pickup Request (B2C parcel vs B2B cargo); legacy rows default to B2B",
    )
    pickup_request_number: Optional[str] = Field(
        default=None,
        sa_column=sa.Column(sa.String(20), nullable=True),
        description="Human-readable 9-digit Pickup ID (Delhivery PUR ID), unique per tenant",
    )
    failure_reason: Optional[str] = Field(
        default=None,
        sa_column=sa.Column(sa.String(255), nullable=True),
        description="Reason recorded when the pickup attempt is marked NOT_PICKED",
    )

    __table_args__ = (
        sa.Index(
            PICKUP_REQUEST_NUMBER_INDEX,
            "tenant_id",
            "pickup_request_number",
            unique=True,
        ),
    )

    # 1-to-Many Relationship: One Truck Manifest bundles N B2B/B2C Shipments ('PickupRequest')
    pickups: List["PickupRequest"] = Relationship(back_populates="manifest")
