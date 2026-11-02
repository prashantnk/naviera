"""add_delivery_exception_ndr_fields

Delhivery-style Delivery Exceptions / NDR module (Phase O.8, X1).

Strictly additive and idempotent (single shared Supabase instance):
  1. New `ndrexceptionreason` enum values (added outside the migration
     transaction because PostgreSQL forbids using a freshly added enum value
     inside the same transaction). Existing values stay; CUSTOMER_UNAVAILABLE
     is treated as an alias of CONSIGNEE_UNAVAILABLE in application code.
  2. pickups.ndr_attempt_count INT NOT NULL DEFAULT 0 (failed attempts).
  3. pickups.ndr_remark VARCHAR(255) NULL (last field-agent remark).
  4. pickups.exception_raised_at TIMESTAMP NULL (server-side aging), backfilled
     for rows currently in EXCEPTION from their latest EXCEPTION activity,
     falling back to updated_at.
  5. pickups.charge_amount NUMERIC(12,2) NULL (freight collection / additional
     charges / weight delta entered by ops when raising the exception).

Wallet ledger types FREIGHT_COLLECTION / ADDITIONAL_CHARGE need no DDL:
wallet_transactions.txn_type is a VARCHAR(50) backed by a Python str Enum.

Revision ID: d1e2f3a4b5c6
Revises: c4e8f1a2b3d5
Create Date: 2026-10-16 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c4e8f1a2b3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_NDR_REASONS = (
    "PAYMENT_DISPUTE",
    "DAMAGED",
    "EWAY_BILL_MISSING",
    "CONSIGNEE_DETAILS_REQUIRED",
    "CONSIGNEE_REFUSED",
    "CONSIGNEE_UNAVAILABLE",
    "DELIVERY_RESCHEDULED",
    "FREIGHT_COLLECTION",
    "ADDITIONAL_CHARGES",
    "WEIGHT_DISCREPANCY",
    "PICKUP_FAILED",
)

BACKFILL_EXCEPTION_RAISED_AT_SQL = """
UPDATE pickups AS p
SET exception_raised_at = COALESCE(
    (
        SELECT MAX(a.timestamp)
        FROM shipment_activities AS a
        WHERE a.pickup_id = p.id
          AND (
              a.activity_type::text = 'EXCEPTION'
              OR (a.diff::jsonb -> 'status' ->> 'new') = 'EXCEPTION'
          )
    ),
    p.updated_at
)
WHERE p.status::text = 'EXCEPTION'
  AND p.exception_raised_at IS NULL
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for reason in NEW_NDR_REASONS:
            op.execute(
                f"ALTER TYPE ndrexceptionreason ADD VALUE IF NOT EXISTS '{reason}'"
            )

    op.execute(
        "ALTER TABLE pickups ADD COLUMN IF NOT EXISTS ndr_attempt_count "
        "INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE pickups ADD COLUMN IF NOT EXISTS ndr_remark VARCHAR(255) NULL"
    )
    op.execute(
        "ALTER TABLE pickups ADD COLUMN IF NOT EXISTS exception_raised_at "
        "TIMESTAMP WITHOUT TIME ZONE NULL"
    )
    op.execute(
        "ALTER TABLE pickups ADD COLUMN IF NOT EXISTS charge_amount NUMERIC(12, 2) NULL"
    )
    op.execute(BACKFILL_EXCEPTION_RAISED_AT_SQL)


def downgrade() -> None:
    # NOTE: PostgreSQL cannot drop single enum values, so the new
    # ndrexceptionreason labels remain. They are harmless once unused.
    op.execute("ALTER TABLE pickups DROP COLUMN IF EXISTS charge_amount")
    op.execute("ALTER TABLE pickups DROP COLUMN IF EXISTS exception_raised_at")
    op.execute("ALTER TABLE pickups DROP COLUMN IF EXISTS ndr_remark")
    op.execute("ALTER TABLE pickups DROP COLUMN IF EXISTS ndr_attempt_count")
