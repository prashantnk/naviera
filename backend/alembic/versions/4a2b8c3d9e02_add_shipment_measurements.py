"""add_shipment_measurements (M-B2)

Phase B. Adds `shipment_measurements`: the boxes, sizes and weight that the
rider (PICKUP), the hub (HUB), an admin (ADMIN) or an accepted weight claim
(CLAIM) actually recorded for a shipment. The single active row per shipment
is the billing basis, so a later edit of the declared boxes cannot undo it.

Spring analogy: a new `@Entity ShipmentMeasurement` with a partial unique
index that plays the role of "at most one `isActive = true` child per parent".

Additive only.

Revision ID: 4a2b8c3d9e02
Revises: 3f9a1c2b7d01
Create Date: 2026-10-27 15:00:01.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "4a2b8c3d9e02"
down_revision: Union[str, Sequence[str], None] = "3f9a1c2b7d01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MEASUREMENT_SOURCES = ("PICKUP", "HUB", "ADMIN", "CLAIM")
"""Mirror of the Python `MeasurementSource(str, Enum)` (models/repricing.py, reprice-core)."""

_SOURCE_LIST_SQL = ", ".join(f"'{source}'" for source in MEASUREMENT_SOURCES)


def upgrade() -> None:
    """Creates `shipment_measurements` with tenant isolation and the one-active-row rule."""
    op.execute(
        f"""
        CREATE TABLE shipment_measurements (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            pickup_id UUID NOT NULL REFERENCES pickups(id) ON DELETE CASCADE,
            source VARCHAR(16) NOT NULL,
            packages JSONB NOT NULL DEFAULT '[]'::jsonb,
            total_boxes INTEGER NOT NULL,
            actual_weight_kg NUMERIC(10, 3) NOT NULL,
            volumetric_weight_kg NUMERIC(10, 3) NOT NULL DEFAULT 0,
            chargeable_weight_kg NUMERIC(10, 3) NOT NULL,
            evidence_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
            remark VARCHAR(255) NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            measured_by_user_id UUID NULL REFERENCES "user"(id) ON DELETE SET NULL,
            measured_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT ck_measurements_source CHECK (source IN ({_SOURCE_LIST_SQL})),
            CONSTRAINT ck_measurements_packages_array CHECK (jsonb_typeof(packages) = 'array'),
            CONSTRAINT ck_measurements_evidence_array CHECK (jsonb_typeof(evidence_urls) = 'array'),
            CONSTRAINT ck_measurements_total_boxes_positive CHECK (total_boxes >= 1),
            CONSTRAINT ck_measurements_weights_non_negative CHECK (
                actual_weight_kg >= 0 AND volumetric_weight_kg >= 0 AND chargeable_weight_kg >= 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_measurements_tenant_id ON shipment_measurements (tenant_id)"
    )
    op.execute(
        "CREATE INDEX ix_measurements_tenant_pickup_measured "
        "ON shipment_measurements (tenant_id, pickup_id, measured_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_measurements_one_active_per_pickup "
        "ON shipment_measurements (pickup_id) WHERE is_active"
    )


def downgrade() -> None:
    """Drops the table. Recorded measurements are lost; bills already saved stay as they are."""
    op.execute("DROP TABLE IF EXISTS shipment_measurements")
