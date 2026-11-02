"""prime_rate_tables (M-P2, pricing redesign D5)

Approved by the user on 2026-10-30 (DESIGN.md v4 §D "M-P2").

Three new tenant-scoped tables for the Logismart Prime rate table (B2B Cargo,
DESIGN §C.2). No existing table changes.

1. `prime_zones`: named delivery areas ("Delhi NCR", "Mumbai") with the sheet's
   city spellings kept as `city_aliases` (JSONB list). Unique (tenant, name).
2. `prime_zone_pincodes`: which pincode belongs to which zone, plus the ODA flag.
   A pincode belongs to at most one zone per tenant (unique tenant + pincode).
3. `prime_lanes`: one transporter's terms for origin zone -> destination zone:
   rate per kg, minimum LR, docket, minimum chargeable weight, volumetric divisor,
   maximum box side, godown/door delivery, ODA / odd-weight / pickup / door-delivery
   per-kg + minimum pairs, markup %, active flag. Money is NUMERIC(10,2). At most one
   ACTIVE lane per (tenant, origin, destination, mode) (partial unique index); the
   inactive rows are competing transporters ops can switch to.

Every table has `tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE`
and deny-all row-level security (no policies: Supabase PostgREST sees nothing;
the backend connects as the table owner, which bypasses RLS).

Side effects: none on existing data. Plain transactional DDL through PgBouncer
(NullPool unchanged). Downgrade drops the three tables (lanes first).

Revision ID: b5c6d7e8f9a0
Revises: 9a1b2c3d4e5f
Create Date: 2026-10-30 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "9a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LANE_MODES = ("SURFACE",)
"""Mirror of `app.models.prime.PrimeLaneMode`."""

DELIVERY_TYPES = ("GODOWN", "DOOR")
"""Mirror of `app.models.prime.PrimeDeliveryType`."""

NEW_TABLES_DROP_ORDER = ("prime_lanes", "prime_zone_pincodes", "prime_zones")
"""Children before parents."""


def _sql_list(values: Sequence[str]) -> str:
    """Renders `'A', 'B'`-style SQL literal lists from trusted constants."""
    return ", ".join(f"'{value}'" for value in values)


def _create_zones() -> None:
    """Creates `prime_zones` (unique zone name per tenant)."""
    op.execute(
        """
        CREATE TABLE prime_zones (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            city_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            CONSTRAINT uq_prime_zones_tenant_name UNIQUE (tenant_id, name),
            CONSTRAINT ck_prime_zones_name_not_blank CHECK (btrim(name) <> ''),
            CONSTRAINT ck_prime_zones_aliases_array CHECK (jsonb_typeof(city_aliases) = 'array')
        )
        """
    )
    op.execute("CREATE INDEX ix_prime_zones_tenant_id ON prime_zones (tenant_id)")


def _create_zone_pincodes() -> None:
    """Creates `prime_zone_pincodes` (one zone per pincode per tenant)."""
    op.execute(
        """
        CREATE TABLE prime_zone_pincodes (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            zone_id UUID NOT NULL REFERENCES prime_zones(id) ON DELETE CASCADE,
            pincode VARCHAR(6) NOT NULL,
            is_oda BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_prime_zone_pincodes_tenant_pincode UNIQUE (tenant_id, pincode),
            CONSTRAINT ck_prime_zone_pincodes_format CHECK (pincode ~ '^[1-9][0-9]{5}$')
        )
        """
    )
    op.execute("CREATE INDEX ix_prime_zone_pincodes_zone_id ON prime_zone_pincodes (zone_id)")


def _create_lanes() -> None:
    """Creates `prime_lanes` with non-negative money CHECKs and the one-active-lane index."""
    op.execute(
        f"""
        CREATE TABLE prime_lanes (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            origin_zone_id UUID NOT NULL REFERENCES prime_zones(id),
            dest_zone_id UUID NOT NULL REFERENCES prime_zones(id),
            mode VARCHAR(20) NOT NULL,
            transporter_name VARCHAR(120) NOT NULL,
            tat_hours INTEGER NOT NULL,
            rate_per_kg NUMERIC(10,2) NOT NULL,
            min_lr_charge NUMERIC(10,2) NOT NULL,
            docket_charge NUMERIC(10,2) NOT NULL,
            min_chargeable_kg NUMERIC(10,2) NOT NULL,
            volumetric_divisor NUMERIC(10,2) NOT NULL,
            max_dimension_cm NUMERIC(10,2) NOT NULL,
            delivery_type VARCHAR(10) NOT NULL,
            oda_per_kg NUMERIC(10,2) NOT NULL,
            oda_min NUMERIC(10,2) NOT NULL,
            odd_weight_per_kg NUMERIC(10,2) NOT NULL,
            odd_weight_min NUMERIC(10,2) NOT NULL,
            pickup_per_kg NUMERIC(10,2) NOT NULL,
            pickup_min NUMERIC(10,2) NOT NULL,
            door_delivery_per_kg NUMERIC(10,2) NOT NULL,
            door_delivery_min NUMERIC(10,2) NOT NULL,
            markup_percent NUMERIC(10,2) NOT NULL DEFAULT 20,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_by UUID NULL REFERENCES "user"(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            CONSTRAINT uq_prime_lanes_tenant_route_transporter
                UNIQUE (tenant_id, origin_zone_id, dest_zone_id, mode, transporter_name),
            CONSTRAINT ck_prime_lanes_mode CHECK (mode IN ({_sql_list(LANE_MODES)})),
            CONSTRAINT ck_prime_lanes_delivery_type
                CHECK (delivery_type IN ({_sql_list(DELIVERY_TYPES)})),
            CONSTRAINT ck_prime_lanes_transporter_not_blank CHECK (btrim(transporter_name) <> ''),
            CONSTRAINT ck_prime_lanes_positive
                CHECK (tat_hours > 0 AND rate_per_kg > 0 AND volumetric_divisor > 0
                       AND max_dimension_cm > 0),
            CONSTRAINT ck_prime_lanes_non_negative
                CHECK (min_lr_charge >= 0 AND docket_charge >= 0 AND min_chargeable_kg >= 0
                       AND oda_per_kg >= 0 AND oda_min >= 0
                       AND odd_weight_per_kg >= 0 AND odd_weight_min >= 0
                       AND pickup_per_kg >= 0 AND pickup_min >= 0
                       AND door_delivery_per_kg >= 0 AND door_delivery_min >= 0
                       AND markup_percent >= 0)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_prime_lanes_one_active ON prime_lanes "
        "(tenant_id, origin_zone_id, dest_zone_id, mode) WHERE is_active"
    )
    op.execute("CREATE INDEX ix_prime_lanes_tenant_id ON prime_lanes (tenant_id)")


def upgrade() -> None:
    """Creates the three Prime tables and enables deny-all RLS on each."""
    _create_zones()
    _create_zone_pincodes()
    _create_lanes()
    for table in reversed(NEW_TABLES_DROP_ORDER):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Drops the three Prime tables (lanes first: they reference zones)."""
    for table in NEW_TABLES_DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table}")
