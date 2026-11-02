"""rename_fleet_pickups_to_manifests

Revision ID: 1ca66faa95e2
Revises: 75b1fa570964
Create Date: 2026-06-28 11:53:35.652141

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '1ca66faa95e2'
down_revision: Union[str, Sequence[str], None] = '75b1fa570964'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename table
    op.rename_table('fleet_pickups', 'manifests')
    
    # Rename enum
    op.execute("ALTER TYPE fleetpickupstatus RENAME TO manifeststatus")
    
    # Rename column
    op.alter_column('pickups', 'fleet_pickup_id', new_column_name='manifest_id')
    
    # Optionally rename index
    op.execute("ALTER INDEX IF EXISTS ix_fleet_pickups_tenant_id RENAME TO ix_manifests_tenant_id")


def downgrade() -> None:
    op.execute("ALTER INDEX IF EXISTS ix_manifests_tenant_id RENAME TO ix_fleet_pickups_tenant_id")
    op.alter_column('pickups', 'manifest_id', new_column_name='fleet_pickup_id')
    op.execute("ALTER TYPE manifeststatus RENAME TO fleetpickupstatus")
    op.rename_table('manifests', 'fleet_pickups')
