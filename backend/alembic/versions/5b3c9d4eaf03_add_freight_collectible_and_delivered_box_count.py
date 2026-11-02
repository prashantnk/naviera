"""add_freight_collectible_and_delivered_box_count (M-B3)

Phase B. Two nullable/defaulted columns on existing tables:
- `payment_details.freight_collectible NUMERIC(12,2) NOT NULL DEFAULT 0`: TO_PAY
  freight the rider still has to collect at the door (R19, R20). It falls when
  the merchant pays it through a Freight Collection exception.
- `pickups.delivered_box_count INTEGER NULL`: boxes actually handed over on a
  Short Shipment partial delivery (R22). NULL = not a partial delivery.

No data backfill: the meaning of `freight_collectible` for existing rows is
owned by RepricingService (reprice-core). On PostgreSQL 11+ adding a column
with a constant default is a metadata-only change (no table rewrite).

Revision ID: 5b3c9d4eaf03
Revises: 4a2b8c3d9e02
Create Date: 2026-10-27 15:00:02.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "5b3c9d4eaf03"
down_revision: Union[str, Sequence[str], None] = "4a2b8c3d9e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Adds the two columns and their non-negative CHECKs."""
    op.execute(
        "ALTER TABLE payment_details "
        "ADD COLUMN freight_collectible NUMERIC(12, 2) NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE payment_details ADD CONSTRAINT ck_payment_details_freight_collectible_non_negative "
        "CHECK (freight_collectible >= 0)"
    )
    op.execute("ALTER TABLE pickups ADD COLUMN delivered_box_count INTEGER NULL")
    op.execute(
        "ALTER TABLE pickups ADD CONSTRAINT ck_pickups_delivered_box_count_non_negative "
        "CHECK (delivered_box_count IS NULL OR delivered_box_count >= 0)"
    )


def downgrade() -> None:
    """Drops both columns (CHECKs go with them). Their values are lost."""
    op.execute("ALTER TABLE pickups DROP COLUMN IF EXISTS delivered_box_count")
    op.execute("ALTER TABLE payment_details DROP COLUMN IF EXISTS freight_collectible")
