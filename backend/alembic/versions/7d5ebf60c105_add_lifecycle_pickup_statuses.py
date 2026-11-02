"""add_lifecycle_pickup_statuses (M-C1)

Phase C (lean). Adds four values to the PostgreSQL enum `pickupstatus`:
- `OUT_FOR_DELIVERY` (placed after `IN_TRANSIT`)
- `RTO_IN_TRANSIT` (placed after `RTO_INITIATED`)
- `RTO_DELIVERED` (placed after `RTO_IN_TRANSIT`)
- `LOST` (placed after `REJECTED_AT_PICKUP`, the current last value)

`ALTER TYPE pickupstatus ADD VALUE` must run outside the migration transaction, so it
runs inside `autocommit_block()` exactly like `a8b9c0d1e2f3`. No rows change
on upgrade.

Downgrade (PostgreSQL cannot drop an enum value): rows using a new value are
mapped back to the closest old value, then the type is rebuilt with the 10
original values in their live order and `pickups.status` (the only column of
this type, verified read-only on 2026-10-27) is converted to it.

Revision ID: 7d5ebf60c105
Revises: 6c4dae5fb004
Create Date: 2026-10-27 15:00:04.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "7d5ebf60c105"
down_revision: Union[str, Sequence[str], None] = "6c4dae5fb004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_STATUS_PLACEMENT = (
    ("OUT_FOR_DELIVERY", "IN_TRANSIT"),
    ("RTO_IN_TRANSIT", "RTO_INITIATED"),
    ("RTO_DELIVERED", "RTO_IN_TRANSIT"),
    ("LOST", "REJECTED_AT_PICKUP"),
)
"""(new value, existing value it is placed after). Order matters: each AFTER target must exist."""

ORIGINAL_STATUSES = (
    "DRAFT",
    "OPEN",
    "ASSIGNED",
    "IN_TRANSIT",
    "COMPLETED",
    "CANCELLED",
    "RTO_INITIATED",
    "EXCEPTION",
    "QC_FAILED",
    "REJECTED_AT_PICKUP",
)
"""The 10 values of `pickupstatus` in the live database before this migration, in live sort order."""

DOWNGRADE_STATUS_MAP = (
    ("OUT_FOR_DELIVERY", "IN_TRANSIT"),
    ("RTO_IN_TRANSIT", "RTO_INITIATED"),
    ("RTO_DELIVERED", "COMPLETED"),
    ("LOST", "IN_TRANSIT"),
)
"""How a row with a new status is stored again by the old code (RTO_DELIVERED was COMPLETED before)."""


def upgrade() -> None:
    """Adds the four enum values, outside a transaction (PostgreSQL rule for ADD VALUE)."""
    with op.get_context().autocommit_block():
        for new_value, after_value in NEW_STATUS_PLACEMENT:
            op.execute(
                f"ALTER TYPE pickupstatus ADD VALUE IF NOT EXISTS '{new_value}' AFTER '{after_value}'"
            )


def downgrade() -> None:
    """Maps rows back, then rebuilds `pickupstatus` without the four values."""
    for new_value, old_value in DOWNGRADE_STATUS_MAP:
        op.execute(
            f"UPDATE pickups SET status = '{old_value}' WHERE status = '{new_value}'"
        )
    original_list_sql = ", ".join(f"'{value}'" for value in ORIGINAL_STATUSES)
    op.execute("ALTER TYPE pickupstatus RENAME TO pickupstatus_m_c1_old")
    op.execute(f"CREATE TYPE pickupstatus AS ENUM ({original_list_sql})")
    op.execute(
        "ALTER TABLE pickups ALTER COLUMN status TYPE pickupstatus "
        "USING status::text::pickupstatus"
    )
    op.execute("DROP TYPE pickupstatus_m_c1_old")
