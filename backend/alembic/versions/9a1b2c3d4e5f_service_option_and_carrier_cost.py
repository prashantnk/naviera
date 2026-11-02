"""service_option_and_carrier_cost (M-P1, pricing redesign D2)

Approved by the user on 2026-10-30 (board #338, DESIGN.md v4 §D "M-P1").

1. `pickups.service_option VARCHAR(40) NOT NULL` + CHECK in
   (`DELHIVERY_SURFACE`, `DELHIVERY_EXPRESS`, `PRIME_SURFACE`): which service was
   booked. Existing rows are back-filled from `service_type` (AIR → DELHIVERY_EXPRESS,
   otherwise DELHIVERY_SURFACE), then the column becomes NOT NULL. A later option is a
   CHECK swap (VARCHAR + CHECK, no PostgreSQL ENUM type, AGENTS §5).
2. `pickups.carrier_awb VARCHAR(40) NULL`: the Delhivery AWB ops paste in. Trimmed and
   non-blank (CHECK) and unique per tenant when set (partial unique index).
3. `payment_details.carrier_cost JSONB NULL`: server-only record of what the carrier
   charges Logismart and the inputs used (never serialised to customers).
4. `shipment_measurements.source` CHECK also allows `CARRIER` (Delhivery's charged weight).
5. New table `delhivery_price_cache` (tenant-scoped Delhivery price answers for the
   30-minute reuse and the 24-hour fallback), deny-all row-level security.

Side effects: none on data beyond the back-fill (live has no shipments). Brief locks;
plain transactional DDL through PgBouncer (NullPool unchanged). Downgrade drops the
new columns and the table and restores the old measurement CHECK.

Revision ID: 9a1b2c3d4e5f
Revises: 7d5ebf60c105
Create Date: 2026-10-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "9a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "7d5ebf60c105"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SERVICE_OPTIONS = ("DELHIVERY_SURFACE", "DELHIVERY_EXPRESS", "PRIME_SURFACE")
"""Mirror of `app.models.pickups.ServiceOption`."""

OLD_MEASUREMENT_SOURCES = ("PICKUP", "HUB", "ADMIN", "CLAIM")
NEW_MEASUREMENT_SOURCES = OLD_MEASUREMENT_SOURCES + ("CARRIER",)
"""Mirror of `app.models.repricing.MeasurementSource`."""


def _sql_list(values: Sequence[str]) -> str:
    """Renders `('A', 'B')`-style SQL literal lists from trusted constants."""
    return ", ".join(f"'{value}'" for value in values)


def _set_measurement_sources(values: Sequence[str]) -> None:
    """Replaces the `shipment_measurements.source` CHECK with the given list."""
    op.execute("ALTER TABLE shipment_measurements DROP CONSTRAINT IF EXISTS ck_measurements_source")
    op.execute(
        "ALTER TABLE shipment_measurements ADD CONSTRAINT ck_measurements_source "
        f"CHECK (source IN ({_sql_list(values)}))"
    )


def upgrade() -> None:
    """Adds the service option, carrier AWB, carrier cost, CARRIER source and the price cache."""
    op.execute("ALTER TABLE pickups ADD COLUMN service_option VARCHAR(40) NULL")
    op.execute(
        "UPDATE pickups SET service_option = CASE WHEN service_type = 'AIR' "
        "THEN 'DELHIVERY_EXPRESS' ELSE 'DELHIVERY_SURFACE' END"
    )
    op.execute("ALTER TABLE pickups ALTER COLUMN service_option SET NOT NULL")
    op.execute(
        "ALTER TABLE pickups ADD CONSTRAINT ck_pickups_service_option_valid "
        f"CHECK (service_option IN ({_sql_list(SERVICE_OPTIONS)}))"
    )

    op.execute("ALTER TABLE pickups ADD COLUMN carrier_awb VARCHAR(40) NULL")
    op.execute(
        "ALTER TABLE pickups ADD CONSTRAINT ck_pickups_carrier_awb_trimmed "
        "CHECK (carrier_awb IS NULL OR (carrier_awb = btrim(carrier_awb) AND carrier_awb <> ''))"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pickups_tenant_carrier_awb ON pickups (tenant_id, carrier_awb) "
        "WHERE carrier_awb IS NOT NULL"
    )

    op.execute("ALTER TABLE payment_details ADD COLUMN carrier_cost JSONB NULL")

    _set_measurement_sources(NEW_MEASUREMENT_SOURCES)

    op.execute(
        """
        CREATE TABLE delhivery_price_cache (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            cache_key VARCHAR(200) NOT NULL,
            request_params JSONB NOT NULL,
            response JSONB NOT NULL,
            fetched_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            CONSTRAINT uq_delhivery_price_cache_tenant_key UNIQUE (tenant_id, cache_key)
        )
        """
    )
    op.execute("ALTER TABLE delhivery_price_cache ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Drops the price cache and the new columns; restores the 4-source measurement CHECK."""
    op.execute("DROP TABLE IF EXISTS delhivery_price_cache")
    op.execute("DELETE FROM shipment_measurements WHERE source = 'CARRIER'")
    _set_measurement_sources(OLD_MEASUREMENT_SOURCES)
    op.execute("ALTER TABLE payment_details DROP COLUMN IF EXISTS carrier_cost")
    op.execute("DROP INDEX IF EXISTS uq_pickups_tenant_carrier_awb")
    op.execute("ALTER TABLE pickups DROP COLUMN IF EXISTS carrier_awb")
    op.execute("ALTER TABLE pickups DROP COLUMN IF EXISTS service_option")
