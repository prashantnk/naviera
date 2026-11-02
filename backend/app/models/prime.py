"""
Logismart Prime rate table (M-P2, DESIGN.md v4 §C.2): zones, zone pincodes and lanes.

Each class maps a table created by migration `b5c6d7e8f9a0`, column for column:
- `prime_zones`: a named delivery area ("Delhi NCR") with the sheet's city spellings.
- `prime_zone_pincodes`: pincode -> zone membership plus the ODA flag (unique per tenant).
- `prime_lanes`: one transporter's cost terms for origin zone -> destination zone.
  At most one ACTIVE lane per (tenant, origin, destination, mode).

Lane numbers are Logismart's transporter COST; the seller's price is cost × (1 + markup)
+ GST, computed in `app.services.pricing`. `transporter_name` and `markup_percent` are
staff-only and never reach a customer response.

Status-like columns are VARCHAR + CHECK in the database and are backed here by Python
`str, Enum` classes (AGENTS §8): code compares enum members, never raw strings.

Spring analogy: three `@Entity` classes; the zone FKs are plain UUID columns
(`@ManyToOne(fetch = LAZY)` without the navigation property).
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

PRIME_MONEY_PRECISION = 10
PRIME_MONEY_SCALE = 2
ZONE_NAME_MAX_LENGTH = 100
PINCODE_LENGTH = 6
LANE_MODE_MAX_LENGTH = 20
TRANSPORTER_NAME_MAX_LENGTH = 120
DELIVERY_TYPE_MAX_LENGTH = 10
DEFAULT_PRIME_MARKUP_PERCENT = Decimal("20.00")
"""DESIGN §A: per-lane markup on the whole Prime cost, default 20 %."""


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime (TIMESTAMP WITHOUT TIME ZONE columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _prime_number_column() -> Column:
    """A NOT NULL NUMERIC(10,2) column (rupees, kg, cm, divisor or percent)."""
    return Column(sa.Numeric(PRIME_MONEY_PRECISION, PRIME_MONEY_SCALE), nullable=False)


def _fk_column(target: str, *, nullable: bool, ondelete: Optional[str] = None, index: bool = False) -> Column:
    """A UUID foreign-key column."""
    return Column(sa.Uuid, sa.ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index)


def _timestamp_column() -> Column:
    """A NOT NULL naive-UTC timestamp column with a server default."""
    return Column(sa.DateTime, nullable=False, server_default=sa.text("(now() AT TIME ZONE 'utc')"))


class PrimeLaneMode(str, Enum):
    """Transport mode of a Prime lane. Mirrors CHECK `ck_prime_lanes_mode` (Sheet1 is all SURFACE)."""

    SURFACE = "SURFACE"


class PrimeDeliveryType(str, Enum):
    """
    Where the transporter hands the goods over at the destination.
    Mirrors CHECK `ck_prime_lanes_delivery_type`.
    """

    GODOWN = "GODOWN"
    """Consignee collects from the transporter's godown; door delivery is a paid add-on."""
    DOOR = "DOOR"
    """Door delivery is already included in the lane rate."""


class PrimeZone(SQLModel, table=True):
    """A named delivery area of one tenant (e.g. "Delhi NCR", "Mumbai")."""

    __tablename__ = "prime_zones"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=_fk_column("tenant.id", nullable=False, ondelete="CASCADE", index=True)
    )
    name: str = Field(sa_column=Column(sa.String(ZONE_NAME_MAX_LENGTH), nullable=False))
    city_aliases: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    created_at: datetime = Field(default_factory=_utc_now_naive, sa_column=_timestamp_column())
    updated_at: datetime = Field(default_factory=_utc_now_naive, sa_column=_timestamp_column())


class PrimeZonePincode(SQLModel, table=True):
    """One pincode's zone membership; `is_oda` adds the ODA charge on deliveries there."""

    __tablename__ = "prime_zone_pincodes"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=_fk_column("tenant.id", nullable=False, ondelete="CASCADE")
    )
    zone_id: uuid.UUID = Field(
        sa_column=_fk_column("prime_zones.id", nullable=False, ondelete="CASCADE", index=True)
    )
    pincode: str = Field(sa_column=Column(sa.String(PINCODE_LENGTH), nullable=False))
    is_oda: bool = Field(
        default=False, sa_column=Column(sa.Boolean, nullable=False, server_default=sa.false())
    )


class PrimeLane(SQLModel, table=True):
    """
    One transporter's cost terms for origin zone -> destination zone (DESIGN §C.3).

    Charges: FREIGHT rate_per_kg × chargeable kg; DOCKET flat; PICKUP max(per_kg × kg, min);
    ODA / ODD_WEIGHT / DOOR_DELIVERY likewise when they apply; the whole leg is topped up to
    `min_lr_charge`. Chargeable kg = max(actual, L×B×H / volumetric_divisor, min_chargeable_kg).
    """

    __tablename__ = "prime_lanes"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=_fk_column("tenant.id", nullable=False, ondelete="CASCADE", index=True)
    )
    origin_zone_id: uuid.UUID = Field(sa_column=_fk_column("prime_zones.id", nullable=False))
    dest_zone_id: uuid.UUID = Field(sa_column=_fk_column("prime_zones.id", nullable=False))
    mode: PrimeLaneMode = Field(sa_column=Column(sa.String(LANE_MODE_MAX_LENGTH), nullable=False))
    transporter_name: str = Field(
        sa_column=Column(sa.String(TRANSPORTER_NAME_MAX_LENGTH), nullable=False)
    )
    tat_hours: int = Field(sa_column=Column(sa.Integer, nullable=False))
    rate_per_kg: Decimal = Field(sa_column=_prime_number_column())
    min_lr_charge: Decimal = Field(sa_column=_prime_number_column())
    docket_charge: Decimal = Field(sa_column=_prime_number_column())
    min_chargeable_kg: Decimal = Field(sa_column=_prime_number_column())
    volumetric_divisor: Decimal = Field(sa_column=_prime_number_column())
    max_dimension_cm: Decimal = Field(sa_column=_prime_number_column())
    delivery_type: PrimeDeliveryType = Field(
        sa_column=Column(sa.String(DELIVERY_TYPE_MAX_LENGTH), nullable=False)
    )
    oda_per_kg: Decimal = Field(sa_column=_prime_number_column())
    oda_min: Decimal = Field(sa_column=_prime_number_column())
    odd_weight_per_kg: Decimal = Field(sa_column=_prime_number_column())
    odd_weight_min: Decimal = Field(sa_column=_prime_number_column())
    pickup_per_kg: Decimal = Field(sa_column=_prime_number_column())
    pickup_min: Decimal = Field(sa_column=_prime_number_column())
    door_delivery_per_kg: Decimal = Field(sa_column=_prime_number_column())
    door_delivery_min: Decimal = Field(sa_column=_prime_number_column())
    markup_percent: Decimal = Field(
        default=DEFAULT_PRIME_MARKUP_PERCENT,
        sa_column=Column(
            sa.Numeric(PRIME_MONEY_PRECISION, PRIME_MONEY_SCALE),
            nullable=False,
            server_default=sa.text("20"),
        ),
    )
    is_active: bool = Field(
        default=True, sa_column=Column(sa.Boolean, nullable=False, server_default=sa.true())
    )
    updated_by: Optional[uuid.UUID] = Field(
        default=None, sa_column=_fk_column("user.id", nullable=True, ondelete="SET NULL")
    )
    created_at: datetime = Field(default_factory=_utc_now_naive, sa_column=_timestamp_column())
    updated_at: datetime = Field(default_factory=_utc_now_naive, sa_column=_timestamp_column())
