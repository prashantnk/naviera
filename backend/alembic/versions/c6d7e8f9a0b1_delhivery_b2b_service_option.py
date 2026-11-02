"""delhivery_b2b_service_option (M-P3, Delhivery B2B Cargo option)

Design accepted by the coordinator 2026-11-01 (board #482/#485); run only after the
user's explicit approval relay (AGENTS.md §2.4).

1. `pickups.service_option` CHECK `ck_pickups_service_option_valid` is swapped to also
   allow `DELHIVERY_B2B_SURFACE` (B2B cargo priced live by Delhivery's B2B freight
   estimate API). VARCHAR(40) + CHECK, no PostgreSQL ENUM type (AGENTS §5).

No new columns or tables and no data rewrite: the Delhivery price cache, the
`payment_details.carrier_cost` JSONB and `pickups.carrier_awb` are reused as-is.

Side effects: a brief ACCESS EXCLUSIVE lock on `pickups` while the new CHECK validates
the existing rows; plain transactional DDL through PgBouncer (NullPool unchanged).
Downgrade restores the 3-value CHECK and refuses while any row uses the new option.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-11-01 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, Sequence[str], None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_pickups_service_option_valid"
NEW_OPTION = "DELHIVERY_B2B_SURFACE"
OLD_SERVICE_OPTIONS = ("DELHIVERY_SURFACE", "DELHIVERY_EXPRESS", "PRIME_SURFACE")
NEW_SERVICE_OPTIONS = OLD_SERVICE_OPTIONS + (NEW_OPTION,)
"""Mirror of `app.models.pickups.ServiceOption`."""


def _sql_list(values: Sequence[str]) -> str:
    """Renders `'A', 'B'`-style SQL literal lists from trusted constants."""
    return ", ".join(f"'{value}'" for value in values)


def _set_service_options(values: Sequence[str]) -> None:
    """Replaces the `pickups.service_option` CHECK with the given list."""
    op.execute(f"ALTER TABLE pickups DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME}")
    op.execute(
        f"ALTER TABLE pickups ADD CONSTRAINT {CONSTRAINT_NAME} "
        f"CHECK (service_option IN ({_sql_list(values)}))"
    )


def upgrade() -> None:
    """Allows the Delhivery B2B Cargo option."""
    _set_service_options(NEW_SERVICE_OPTIONS)


def downgrade() -> None:
    """Restores the 3-option CHECK; refuses while a shipment is booked on the B2B option."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pickups WHERE service_option = '{NEW_OPTION}') THEN
                RAISE EXCEPTION 'Shipments use {NEW_OPTION}; re-book them before downgrading M-P3.';
            END IF;
        END $$;
        """
    )
    _set_service_options(OLD_SERVICE_OPTIONS)
