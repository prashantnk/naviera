"""add_pickup_request_flow_to_manifests

Delhivery-style Pickup Requests (PUR) for both B2C and B2B flows.

Strictly additive and idempotent (single shared Supabase instance):
  1. manifests.service_flow VARCHAR(8) NOT NULL DEFAULT 'B2B'
     (every pre-existing manifest is a B2B fleet pickup).
  2. manifests.pickup_request_number VARCHAR(20) NULL, backfilled with a
     unique 9-digit numeric Pickup ID, plus a unique index on
     (tenant_id, pickup_request_number).
  3. manifests.failure_reason VARCHAR(255) NULL ("Not Picked" reason).
  4. manifeststatus enum value 'NOT_PICKED' (added outside the migration
     transaction because PostgreSQL forbids using a freshly added enum value
     inside the same transaction).

Revision ID: c4e8f1a2b3d5
Revises: b7c8d9e0f1a2
Create Date: 2026-10-16 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4e8f1a2b3d5"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PUR_NUMBER_INDEX_NAME = "uq_manifests_tenant_pickup_request_number"

# Backfill strategy for the 9-digit Pickup ID:
#   number = 300000000 + row_number * 7919 + random(0 .. 7918)
# Each row owns a disjoint block of 7919 numbers, so values are globally
# unique without a retry loop, and stay 9 digits for up to ~88k rows.
BACKFILL_PUR_NUMBERS_SQL = """
UPDATE manifests AS m
SET pickup_request_number = numbered.pur_number
FROM (
    SELECT
        id,
        (
            300000000
            + ROW_NUMBER() OVER (ORDER BY created_at, id) * 7919
            + FLOOR(RANDOM() * 7919)::BIGINT
        )::TEXT AS pur_number
    FROM manifests
    WHERE pickup_request_number IS NULL
) AS numbered
WHERE m.id = numbered.id
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE manifests ADD COLUMN IF NOT EXISTS service_flow "
        "VARCHAR(8) NOT NULL DEFAULT 'B2B'"
    )
    op.execute(
        "ALTER TABLE manifests ADD COLUMN IF NOT EXISTS pickup_request_number "
        "VARCHAR(20) NULL"
    )
    op.execute(BACKFILL_PUR_NUMBERS_SQL)
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {PUR_NUMBER_INDEX_NAME} "
        "ON manifests (tenant_id, pickup_request_number)"
    )
    op.execute(
        "ALTER TABLE manifests ADD COLUMN IF NOT EXISTS failure_reason "
        "VARCHAR(255) NULL"
    )
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE manifeststatus ADD VALUE IF NOT EXISTS 'NOT_PICKED'")


def downgrade() -> None:
    # NOTE: PostgreSQL cannot drop a single enum value, so 'NOT_PICKED' stays in
    # the manifeststatus type. It is harmless once no row references it.
    op.execute(f"DROP INDEX IF EXISTS {PUR_NUMBER_INDEX_NAME}")
    op.execute("ALTER TABLE manifests DROP COLUMN IF EXISTS failure_reason")
    op.execute("ALTER TABLE manifests DROP COLUMN IF EXISTS pickup_request_number")
    op.execute("ALTER TABLE manifests DROP COLUMN IF EXISTS service_flow")
